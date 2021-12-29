run-dev:
	FLASK_ENV=development FLASK_APP=landrush poetry run flask run -p 5001 --extra-files=landrush/schema.sql
