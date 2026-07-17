import socket
import webbrowser

import uvicorn


def main():
    hostname = socket.gethostname()
    print(f"DPR starting — open http://localhost:8765 or http://{hostname}:8765 from another laptop on the same wifi")
    webbrowser.open("http://localhost:8765")
    uvicorn.run("app.web:create_app", factory=True, host="0.0.0.0", port=8765)


if __name__ == "__main__":
    main()
