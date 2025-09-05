import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.support import expected_conditions as EC

# WebDriver를 매번 새로 생성하지 않고, 필요한 경우에만 생성하도록 관리할 수 있습니다.
# 하지만 웹 요청마다 브라우저를 띄우는 것은 매우 비효율적이므로,
# 이 함수는 반드시 백그라운드에서 비동기적으로 실행되어야 합니다.

def riro_login_check_teacher(riro_id, riro_pw):
    """
    성공 시: {'status': 'success', 'name': '이름'}
    실패 시: {'status': 'error', 'message': '에러 메시지'}
    """
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')  # UI 없이 백그라운드에서 실행
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = None
    try:
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
        driver.get("https://iscience.riroschool.kr/")

        # 로그인 페이지로 이동
        login_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="container"]/div/div/div[5]/div/p[2]/a'))
        )
        login_button.click()

        # ID/PW 입력 및 로그인 시도
        id_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'id')))
        pw_box = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'pw')))

        id_box.send_keys(riro_id)
        pw_box.send_keys(riro_pw)

        send_button = driver.find_element(By.XPATH, '//*[@id="container"]/div/section/div[2]/div[2]/form/button')
        send_button.click()

        # 로그인 실패 알림 확인
        try:
            WebDriverWait(driver, 0.5).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            error_message = alert.text
            alert.accept()
            return {'status': 'error', 'message': '로그인 실패: ' + error_message}
        except TimeoutException:
            pass # 알림이 없으면 성공

        # 개인정보 페이지로 이동
        info_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="container"]/div/div/div[5]/div[1]/div[2]/div/div/a[1]'))
        )
        info_button.click()

        # 개인정보 확인을 위한 비밀번호 재입력
        pw_box_info = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, 'pw')))
        pw_box_info.send_keys(riro_pw)

        send_button_info = driver.find_element(By.XPATH, '//*[@id="container"]/div/form/div/button[2]')
        send_button_info.click()

        # 정보 추출 (XPath는 교사 정보에 맞게 수정 필요)
        name = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="container"]/div/form/div[2]/table/tbody/tr[1]/td[2]/div/div'))
        ).text

        return {'status': 'success', 'name': name}

    except TimeoutException:
        return {'status': 'error', 'message': '페이지 로딩 시간 초과. 리로스쿨 서버가 응답하지 않을 수 있습니다.'}
    except NoSuchElementException:
        return {'status': 'error', 'message': '페이지 구조가 변경되어 요소를 찾을 수 없습니다. 관리자에게 문의하세요.'}
    except Exception as e:
        return {'status': 'error', 'message': f'알 수 없는 오류 발생: {str(e)}'}
    finally:
        if driver:
            driver.quit()

# 예시 사용법
if __name__ == "__main__":
    # 이 파일은 직접 실행되지 않도록 pass 처리합니다.
    pass