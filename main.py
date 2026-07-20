import os
import socket
import webbrowser

import uvicorn


def main():
    hostname = socket.gethostname()
    print(f"DPR starting — open http://localhost:8765 or http://{hostname}:8765 from another laptop on the same wifi")
    if os.environ.get("DPR_AUTO_OPEN_BROWSER", "1") != "0":
        webbrowser.open("http://localhost:8765")
    uvicorn.run("app.web:create_app", factory=True, host="0.0.0.0", port=8765)


if __name__ == "__main__":
    main()
