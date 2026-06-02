from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import csv
import time
import os
import sys
import tempfile
import shutil
from selenium.common.exceptions import SessionNotCreatedException

app = Flask(__name__)

DEFAULT_CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def create_driver(use_temp_profile: bool = True):
    options = Options()

    if use_temp_profile:
        profile_dir = tempfile.mkdtemp(prefix="selenium_profile_")
        options.add_argument(f"--user-data-dir={profile_dir}")
    else:
        profile_dir = None

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")

    # Only set binary if it exists on disk
    if os.path.exists(DEFAULT_CHROME_BINARY):
        options.binary_location = DEFAULT_CHROME_BINARY

    chromedriver_path = ChromeDriverManager().install()
    log_path = os.path.join(os.getcwd(), "chromedriver.log")
    service = Service(chromedriver_path, log_path=log_path)

    try:
        driver = webdriver.Chrome(service=service, options=options)
    except SessionNotCreatedException as e:
        # propagate a clear exception
        raise RuntimeError(
            f"Could not start Chrome. See {log_path} for details. Original: {e}"
        )

    return driver, profile_dir


@app.route("/scrape")
def scrape():
    url = request.args.get("url")
    max_pages = int(request.args.get("pages", 20))

    if not url:
        return jsonify({"error": "missing url parameter"}), 400

    # Use a temporary profile by default to avoid profile locks
    try:
        driver, profile_dir = create_driver(use_temp_profile=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        driver.get(url)

        data = []

        for _ in range(max_pages):
            rows = driver.find_elements(By.CSS_SELECTOR, "table tbody tr")
            for row in rows:
                cols = row.find_elements(By.TAG_NAME, "td")
                data.append([c.text.strip() for c in cols])

            # Try to click next page control
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, "button[aria-label='Next page']")
                if next_btn.is_enabled():
                    next_btn.click()
                    time.sleep(2)
                    continue
                else:
                    break
            except Exception:
                break

        # Save CSV
        out_path = os.path.join(os.getcwd(), "results.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(data)

        return jsonify({"status": "ok", "rows": len(data), "csv": out_path})

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        if profile_dir:
            try:
                shutil.rmtree(profile_dir)
            except Exception:
                pass


if __name__ == "__main__":
    # Only start the server when executed directly
    import socket

    def _is_port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return True
            except OSError:
                return False

    DEFAULT_PORT = 5000
    port_env = os.getenv("PORT")

    if port_env:
        try:
            desired_port = int(port_env)
        except ValueError:
            print(f"Invalid PORT value: {port_env}, falling back to {DEFAULT_PORT}")
            desired_port = DEFAULT_PORT

        if _is_port_free(desired_port):
            port = desired_port
        else:
            print(f"Port {desired_port} is in use; selecting a free port instead.")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                port = s.getsockname()[1]
    else:
        if _is_port_free(DEFAULT_PORT):
            port = DEFAULT_PORT
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                port = s.getsockname()[1]
            print(f"Port {DEFAULT_PORT} in use; using free port {port} instead.")

    print(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port)
