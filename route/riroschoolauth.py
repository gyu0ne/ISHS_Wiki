from fastapi import FastAPI, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
import requests, time
from bs4 import BeautifulSoup

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.post("/api/riro_login")
def riro_login(id: str = Form(...), password: str = Form(...)):
    s = requests.Session()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome"
    }

    SLEEP_SEC = 2
    MAX_RETRIES = 3
    last_exception = None

    for _ in range(MAX_RETRIES):
        try:
            try:
                s.get("https://iscience.riroschool.kr/user.php?action=user_logout", timeout=10)
            except requests.RequestException:
                pass

            r = s.post(
                "https://iscience.riroschool.kr/ajax.php",
                headers=headers,
                data={
                    "app": "user", "mode": "login", "userType": "1",
                    "id": id, "pw": password, "deeplink": "", "redirect_link": ""
                },
                timeout=15,
            )

            try:
                login_json = r.json()
            except ValueError:
                raise RuntimeError("Not JSON response")

            code = str(login_json.get("code"))
            if code == "902":
                return {"status": "error", "message": "아이디 또는 비밀번호가 틀렸습니다."}
            if code != "000":
                raise RuntimeError(f"로그인 실패 code={code}")

            token = login_json.get("token")
            if not token:
                raise RuntimeError("Token not found")

            r2 = s.post(
                "https://iscience.riroschool.kr/user.php",
                headers=headers,
                data={"pw": password},
                cookies={"cookie_token": token},
                allow_redirects=False,
                timeout=15,
            )
            html = r2.text
            soup = BeautifulSoup(html, "html.parser")

            el_student = soup.select_one("span.m_level3")
            if not el_student:
                el_student = soup.select_one("span.m_level1")
            inputs = soup.select(".input_disabled")

            if not el_student or len(inputs) < 2:
                raise RuntimeError("Cannot parse user info")

            student = el_student.get_text(strip=True) or ""
            name = (inputs[0].get_text(strip=True) or "")
            student_number_raw = (inputs[1].get_text(strip=True) or "")

            if len(student_number_raw) >= 3:
                student_number = student_number_raw[0] + student_number_raw[2:]
            else:
                student_number = student_number_raw

            generation = 0
            if len(id) >= 2 and id[:2].isdigit():
                generation = int("20" + id[:2]) - 1994 + 1

            if all([name, student_number, student]) and generation > 0:
                return {
                    "status": "success",
                    "name": name,
                    "student_number": student_number,
                    "generation": generation,
                    "student": student,
                }

            raise RuntimeError("Data missing. Retrying...")

        except (requests.RequestException, RuntimeError) as e:
            last_exception = e
            # print("Error:", e) # 콘솔 출력 제거
            time.sleep(SLEEP_SEC)
            
    return {"status": "error", "message": f"인증 서버와 통신 중 오류가 발생했습니다."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5001)
