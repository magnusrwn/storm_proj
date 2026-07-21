from fastapi import FastAPI
from logger_config import configure_logging


configure_logging()

app = FastAPI()
