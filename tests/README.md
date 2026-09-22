# Python 테스트

모든 명령은 저장소 루트에서 실행합니다. Python 3.11 또는 3.12와 `requirements-test.txt`의 의존성이 필요합니다. 테스트 러너는 표준 라이브러리 `unittest`이며 pytest는 필요하지 않습니다.

`requirements-test.txt`는 기존 애플리케이션 의존성을 포함하고, 폼 파서의 버전별 동작을 재현하기 위해 검증한 Flask 3.1.3 / Werkzeug 3.1.8을 고정합니다. Flask의 async 지원과 BeautifulSoup도 포함됩니다. 운영 의존성 파일은 변경하지 않습니다.

## 전체 테스트

uv가 설치되어 있으면 아래 명령으로 Python 버전과 의존성을 선택해 실행할 수 있습니다.

```sh
uv run --no-project --python 3.11 --with-requirements requirements-test.txt python -m unittest discover -s tests -t . -p "test_*.py" -v
uv run --no-project --python 3.12 --with-requirements requirements-test.txt python -m unittest discover -s tests -t . -p "test_*.py" -v
```

위 명령의 테스트 실행 부분은 의존성이 설치된 Python 환경에서도 동일합니다.

```sh
python -m unittest discover -s tests -t . -p "test_*.py" -v
```

## 이번 PR의 테스트만 실행

```sh
uv run --no-project --python 3.12 --with-requirements requirements-test.txt python -m unittest tests.test_editor_form tests.test_form_limits -v
```

`python -m unittest tests.test_editor_form`처럼 패키지 이름으로 개별 실행하거나, `python -m unittest discover -s tests -p "test_*.py"`로 실행해도 됩니다. 별도의 `PYTHONPATH` 설정은 필요하지 않습니다.

## 테스트 격리 및 검증 범위

- 편집기·수식 렌더러 테스트는 임시 디렉터리의 버전 파일과 메모리 SQLite DB를 사용합니다. 운영 DB, Go 서버, 로그인 계정은 필요하지 않습니다.
- import 중 자동 의존성 설치와 프로세스 종료는 실패하도록 막습니다. 설치가 성공한 뒤에만 실행되는 애플리케이션 재시작도 이 단계에서 차단됩니다.
- `subprocess.Popen` 전체를 모킹하지 않습니다. Windows의 표준 라이브러리가 OS 정보를 조회하는 `ver` 호출까지 가로채 테스트 import가 실패하던 원인을 제거했습니다.
- 폼 제한 테스트는 실제 `app.py`의 설정·요청 훅·라우팅을 불러오고, 저장 핸들러는 폼 파싱을 확인하는 테스트 핸들러로 대체합니다. 운영 DB 저장과 실제 인증 서버까지 검증하는 테스트는 아닙니다.

검증 기준: Windows에서 Python 3.11.15 / 3.12.13 각각 전체 23개 테스트. Linux 실행 결과는 아직 확인하지 않았습니다.
