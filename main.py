import logging
from dotenv import load_dotenv

load_dotenv()

from src.bot import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

if __name__ == "__main__":
    log.info("Iniciando WebScribeBot...")
    app = create_app()
    app.run()