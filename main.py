from fastapi import FastAPI
import uvicorn

def main():
    server = FastAPI()
    uvicorn.run(
        server,
        host="127.0.0.1",
        port=3072
    )


if __name__ == "__main__":
    main()
