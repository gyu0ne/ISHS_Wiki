from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests, time, re
from bs4 import BeautifulSoup

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

class LoginRequest(BaseModel):
    id: str
    password: str

# ============================================================
# 교원 판별용 상수
# ============================================================
TEACHER_KEYWORDS     = ['교원', '교사', '교직원', '선생']
STUDENT_ANTI_KEYWORDS = ['학생', '학부', '졸업']


def _is_teacher_role(text: str) -> bool:
    """
    신분 텍스트가 교원에 해당하는지 판별.
    - 교원 키워드가 하나라도 있고
    - 학생/졸업 키워드가 없어야 교원으로 처리.
    """
    return (
        any(kw in text for kw in TEACHER_KEYWORDS) and
        not any(kw in text for kw in STUDENT_ANTI_KEYWORDS)
    )


def _parse_student_number(raw: str) -> str:
    """
    리로스쿨 학번 포맷 정규화.
    - 리로스쿨 학번 형식: 예) 3101 → 301 (학년 + 반/번호, 2번째 자리 제거)
    - 숫자로만 이루어진 경우에만 변환 적용.
    - 그 외 포맷(예: "3학년 1반 1번", 졸업생, 교사 등)은 원문 반환.
    """
    if raw.isdigit() and len(raw) >= 3:
        # 예: "3101" → "3" + "01" = "301"
        return raw[0] + raw[2:]
    return raw


def _calc_generation(riro_id: str) -> int:
    """
    리로스쿨 아이디 앞 2자리로 기수를 계산.
    - 예: "24xxxx" → 2024 - 1994 + 1 = 31기
    - 앞 2자리가 숫자가 아니면 0 반환.
    """
    if len(riro_id) >= 2 and riro_id[:2].isdigit():
        return int("20" + riro_id[:2]) - 1994 + 1
    return 0


def _extract_input_texts(soup: BeautifulSoup) -> list:
    """
    마이페이지에서 이름/학번 등의 텍스트를 순서대로 추출.

    우선순위:
      1) class="input_disabled" div/span 요소의 텍스트
      2) input[readonly], input[disabled] 요소의 value 속성
    """
    texts = []

    # 1순위: .input_disabled 요소 (리로스쿨 기본 구조)
    for el in soup.select(".input_disabled"):
        val = el.get_text(strip=True)
        if val:
            texts.append(val)

    if texts:
        return texts

    # 2순위: readonly/disabled input 태그의 value 속성
    for el in soup.select("input[readonly], input[disabled]"):
        val = (el.get("value") or "").strip()
        if val:
            texts.append(val)

    return texts


def _parse_normal(soup: BeautifulSoup, user_id: str) -> dict | None:
    """
    일반 계정(normal) 마이페이지 파싱.
    반환: 성공 시 info dict, 실패 시 None.
    """
    # ── 1. 신분 텍스트 추출 ──────────────────────────────────────
    # 리로스쿨은 .m_level1(일반 학생), .m_level3(재학생), .m_level2(교원 등) 사용.
    el_student = soup.select_one("span.m_level3, span.m_level1, span.m_level2")
    student = el_student.get_text(strip=True) if el_student else ""

    # ── 2. 이름·학번 추출 ────────────────────────────────────────
    input_texts = _extract_input_texts(soup)
    if not input_texts:
        return None  # 파싱 실패 → 재시도

    name = input_texts[0]
    if not name:
        return None

    # ── 3. 교원 판별 ─────────────────────────────────────────────
    if _is_teacher_role(student):
        return {
            "status": "success",
            "name": name,
            "student_number": "교사",
            "generation": 0,
            "student": student or "교사",
            "is_teacher": True,
        }

    # ── 4. 학생/졸업생 처리 ──────────────────────────────────────
    student_number_raw = input_texts[1] if len(input_texts) >= 2 else ""
    student_number = _parse_student_number(student_number_raw)

    # 기수: 아이디 앞 2자리 우선, 실패 시 학번 앞 2자리
    generation = _calc_generation(user_id)
    if generation == 0 and student_number_raw.isdigit() and len(student_number_raw) >= 4:
        generation = _calc_generation(student_number_raw)

    # 이름만 있어도 성공 반환 (학번/기수 없는 졸업생 케이스 포함)
    if name:
        return {
            "status": "success",
            "name": name,
            "student_number": student_number or "학생",
            "generation": generation,
            "student": student or "학생",
            "is_teacher": False,
        }

    return None


def _parse_integrated(soup: BeautifulSoup, user_id: str) -> dict | None:
    """
    통합 계정(integrated) 마이페이지 파싱.
    반환: 성공 시 info dict, 실패 시 None.
    """
    # ── 1. 신분 텍스트 및 리로 ID 추출 ──────────────────────────
    # .elem_fix 의 텍스트 형식: "25춘향동  학생 재학중"  (앞 8 글자 = 리로 ID)
    riro_id = ""
    student = ""
    elem_fixes = soup.select(".elem_fix")
    if elem_fixes:
        raw_text = elem_fixes[0].get_text()
        riro_id  = raw_text[:8].strip()
        # 15번째 글자부터 ~ 마지막 직전까지가 신분 텍스트 (형식이 바뀔 수 있으니 후처리)
        student  = raw_text[15:-1].strip() if len(raw_text) > 15 else ""

    # ── 2. 이름·학번 추출 ────────────────────────────────────────
    input_texts = _extract_input_texts(soup)
    if not input_texts:
        return None

    name = input_texts[0]
    if not name:
        return None

    # ── 3. 교원 판별 ─────────────────────────────────────────────
    if _is_teacher_role(student):
        return {
            "status": "success",
            "name": name,
            "student_number": "교사",
            "generation": 0,
            "student": student or "교사",
            "is_teacher": True,
        }

    # ── 4. 학생/졸업생 처리 ──────────────────────────────────────
    student_number_raw = input_texts[1] if len(input_texts) >= 2 else ""
    student_number = _parse_student_number(student_number_raw)

    # 기수: 리로 ID 앞 2자리 우선, 실패 시 user_id, 그 다음 학번
    generation = _calc_generation(riro_id) or _calc_generation(user_id)
    if generation == 0 and student_number_raw.isdigit() and len(student_number_raw) >= 4:
        generation = _calc_generation(student_number_raw)

    if name:
        return {
            "status": "success",
            "name": name,
            "student_number": student_number or "학생",
            "generation": generation,
            "student": student or "학생",
            "is_teacher": False,
        }

    return None


def check_riro_login(user_id: str, user_pw: str) -> dict:
    """
    리로스쿨 로그인 및 사용자 정보 파싱.

    반환 형식 (성공):
        {
            "status": "success",
            "name": str,           # 실명
            "student_number": str, # 학번 (교원이면 "교사")
            "generation": int,     # 기수 (교원이면 0)
            "student": str,        # 신분 텍스트 (예: "재학생", "졸업생", "교사")
            "is_teacher": bool,    # 교원 여부
        }

    반환 형식 (실패):
        {"status": "error", "message": str}
    """
    s = requests.Session()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome"
        ),
    }

    SLEEP_SEC  = 2
    MAX_RETRIES = 5
    last_error = "알 수 없는 오류"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # ── 로그아웃 (세션 초기화) ──────────────────────────
            try:
                s.post(
                    "https://iscience.riroschool.kr/user.php?action=user_logout",
                    timeout=10,
                )
            except requests.RequestException:
                pass  # 로그아웃 실패는 무시

            # ── 로그인 요청 ─────────────────────────────────────
            r = s.post(
                "https://iscience.riroschool.kr/ajax.php",
                headers=headers,
                data={
                    "app": "user", "mode": "login", "userType": "1",
                    "id": user_id, "pw": user_pw,
                    "deeplink": "", "redirect_link": "",
                },
                timeout=15,
            )

            # ── 로그인 응답 파싱 ─────────────────────────────────
            try:
                login_json = r.json()
            except ValueError:
                return {"status": "error", "message": "인증 서버에서 잘못된 응답을 받았습니다."}

            code = str(login_json.get("code"))
            if code == "902":
                # 아이디/패스워드 오류는 재시도 없이 즉시 반환
                return {"status": "error", "message": "아이디 또는 비밀번호가 틀렸습니다."}
            if code != "000":
                return {"status": "error", "message": f"로그인 실패 (code={code})"}

            token = login_json.get("token")
            if not token:
                last_error = f"[시도 {attempt}] 토큰을 받지 못했습니다."
                time.sleep(SLEEP_SEC)
                continue

            # ── 마이페이지 요청 ──────────────────────────────────
            r2 = s.post(
                "https://iscience.riroschool.kr/user.php",
                headers=headers,
                data={"pw": user_pw},
                cookies={"cookie_token": token},
                allow_redirects=False,
                timeout=15,
            )
            soup = BeautifulSoup(r2.text, "html.parser")

            # ── 계정 유형 판별 ───────────────────────────────────
            # .td_title 의 첫 요소가 "통합아이디"이면 통합 계정
            account_type = "normal"
            try:
                first_title = soup.select(".td_title")[0].get_text(strip=True)
                if first_title == "통합아이디":
                    account_type = "integrated"
            except (IndexError, AttributeError):
                pass  # 판별 실패 시 normal 로 처리

            # ── 계정 유형별 파싱 ─────────────────────────────────
            if account_type == "normal":
                result = _parse_normal(soup, user_id)
            else:  # integrated
                result = _parse_integrated(soup, user_id)

            if result:
                return result

            # 파싱 결과가 None → 재시도
            last_error = f"[시도 {attempt}] 마이페이지 데이터 파싱 실패 (account_type={account_type})"
            time.sleep(SLEEP_SEC)

        except requests.RequestException as e:
            last_error = f"[시도 {attempt}] 네트워크 오류: {e}"
            time.sleep(SLEEP_SEC)
        except Exception as e:
            last_error = f"[시도 {attempt}] 예외 발생: {e}"
            time.sleep(SLEEP_SEC)

    # 모든 재시도 실패
    return {
        "status": "error",
        "message": f"인증 서버와 통신 중 오류가 발생했습니다. ({last_error})",
    }


@app.post("/api/riro_login")
def riro_login_api(req: LoginRequest):
    return check_riro_login(req.id, req.password)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
