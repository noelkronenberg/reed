from models import db
from index import app, logger

with app.app_context():
    db.drop_all()
    logger.debug("Dropped all tables")
    
    db.create_all()
    logger.debug("Created all tables") 