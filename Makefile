run-dev:
	FLASK_ENV=development poetry run flask run -p 5001 --extra-files=landrush/schema.sql
