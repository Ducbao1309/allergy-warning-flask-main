"""Send a synthetic multipart probe to the local scan endpoint without Gemini."""

import http.client
import sys
import uuid


HOST = "127.0.0.1"
PORT = 5000
PATH = "/scan/process"


def main():
    boundary = f"----ScanUploadProbe{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="image"; filename="probe.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode("ascii")
    body += b"Not a real image; this unauthenticated probe stops before Gemini.\r\n"
    body += f"--{boundary}--\r\n".encode("ascii")

    connection = http.client.HTTPConnection(HOST, PORT, timeout=5)
    try:
        connection.request(
            "POST",
            PATH,
            body=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        response.read()
        print(f"POST http://{HOST}:{PORT}{PATH} -> {response.status}")
        print(f"Location: {response.getheader('Location')}")
        if response.status in (301, 302, 303, 307, 308):
            print("Redirect received; the unauthenticated request was handled before Gemini.")
        elif response.status == 404:
            print("Endpoint not found on this Flask process.")
            return 1
        return 0
    except OSError as error:
        print(f"HTTP probe failed: {type(error).__name__}: {error}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
