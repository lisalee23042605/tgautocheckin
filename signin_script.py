import os
import time
from telethon import TelegramClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from PIL import Image
import io

# 从环境变量获取敏感信息
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
TARGET_BOT = os.getenv('TARGET_BOT')
START_CMD = '/start'
CONTROL_CHAT = 'me'  # 控制发送截图的目标聊天
BUTTON_TEXT = '签到'  # 按钮文字
YOUR_CHAT_ID = os.getenv('YOUR_CHAT_ID')  # 发送截图的目标聊天 ID

# 设置 Telethon 客户端
client = TelegramClient('session_name', API_ID, API_HASH)

# 设置无头模式的 Chrome WebDriver
chrome_options = Options()
chrome_options.add_argument('--headless')  # 不显示浏览器界面
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')

# 启动浏览器并截图
def sign_in():
    client.start()
    
    # 给目标 Bot 发送 /start 命令
    client.send_message(TARGET_BOT, START_CMD)

    # 查找签到按钮并点击
    message = client.get_messages(TARGET_BOT, limit=1)
    if BUTTON_TEXT in message[0].text:
        client.send_message(CONTROL_CHAT, '签到成功！')
        take_screenshot()

def take_screenshot():
    driver = webdriver.Chrome(options=chrome_options)
    driver.get('https://your-sign-in-page-url')  # 填写目标 URL

    # 定位签到按钮并点击
    sign_in_button = driver.find_element(By.XPATH, '//button[contains(text(), "签到")]')  # 定位按钮
    sign_in_button.click()

    # 等待页面加载并截图
    time.sleep(2)
    screenshot = driver.get_screenshot_as_png()
    send_screenshot_to_telegram(screenshot)
    driver.quit()

def send_screenshot_to_telegram(screenshot):
    image = Image.open(io.BytesIO(screenshot))
    temp_image_path = '/tmp/screenshot.png'
    image.save(temp_image_path)

    # 发送截图到指定 Telegram
    with open(temp_image_path, 'rb') as file:
        client.send_file(CONTROL_CHAT, file, caption="签到截图")

if __name__ == "__main__":
    sign_in()
