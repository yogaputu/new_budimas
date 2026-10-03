from datetime import timedelta

from apps import native_db
from flask import request

from apps.lib.helper import date_now_obj, date_now
from apps.lib.query import DB
from flask_httpauth import HTTPTokenAuth
from flask import abort
from sqlalchemy import text

token_auth = HTTPTokenAuth()

@token_auth.verify_token
def verify_token(token):
    """
     Verify that the token is valid. This is a non - standard way to verify a token but it does not make sense to use it for any user.
     
     @param token - The token to verify. Must be lowercase.
     
     @return True if the token is valid False otherwise. If the token is invalid abort with 403 ( Forbidden )
    """
    
    if not token:
        return False

    with native_db.engine.connect() as conn:
        result = conn.execute(
            text("SELECT tokens FROM users WHERE tokens = :token"),
            {"token": token}
        ).fetchone()

    return bool(result)

class BaseServices():
    def __init__(self):
        """
         Initialize the database. This is called by __init__ and should not be called directly by user code
        """
        self.db = native_db
        
        # TODO change this propertie to True if in development
        self.is_production = True
        
        self.super_user_email = ['superusersolo@super.user', 'superuserwonogiri@super.user']
        self.super_user_username = ['super user solo', 'super user wonogiri']
        self.super_user_query = f"""
            SELECT
            users.tokens AS token, users.id AS id_user,
            sales.id AS id_sales,
            users.nama AS nama_user,
            users.email AS user_email,
            users.password
            FROM
            users
            JOIN sales ON users.id = sales.id_user
            JOIN driver on users.id = driver.id_user
            WHERE
            users.email = :email
        """
    
    def query(self): return DB()
    """
     Returns a DB object to be used for querying the database. This is a no - op for databases that don't support queries.
     
     
     @return A : class : ` DB ` object that can be used to query the database or None if there is no
    """
    
    def req(self, param): 
        """
         Get a parameter from the request. This is used to determine if we are dealing with a POST or GET request
         
         @param param - Name of parameter to look for
         
         @return Value of parameter or None if not found or not JSON or JSON - encoded data ( in which case it will be None )
        """
        json_data = request.get_json(silent=True)

        # Return the value of the parameter in the json_data.
        if json_data and param in json_data:
            return json_data[param]
        

        # Get the value of a parameter.

        if param in request.args:
            return request.args.get(param)
        

        # Get the value of a parameter in the form.

        if param in request.form:
            return request.form.get(param)
        
        return None
    
    def commit(self):
        """
         Commit changes to the database. This is a no - op if there are no changes to be committed.
         
         
         @return The : class : `. Session ` object for chaining. code - block :: python import paddle
        """
        self.db.session.commit()
        
        return self
    
    def flush(self):
        """
         Flush the session. This is useful for tests that need to be re - executed in order to ensure that the session is flushed before a test is executed.
         
         
         @return The : class : ` _orm. Session ` for chaining purposes. code - block :: python import sqlalchemy as
        """
        self.db.session().flush()
        
        return self
    
    def add(self, obj):
        """
         Add a row to the database. This is a convenience method for adding an object to the database.
         
         @param obj - The object to add. It must have a __dict__ method that returns a dictionary.
         
         @return The instance to allow chaining method calls :. from sqlalchemy import session from sqlalchemy. orm import
        """
        self.db.session.add(obj)
        
        return self
    
    def delete(self, obj):
        """
         Delete a row from the database. This is a convenience method for deleting an object from the database.
         
         @param obj - The object to delete. It must have a __dict__ method that returns a dictionary.
         
         @return The instance to allow chaining method calls :. from sqlalchemy import session from sqlalchemy. orm import
        """
        self.db.session.delete(obj)
        
        return self

    def check_is_periode_closed(self):
        """
         To check is close periode for all services
        """

        authorization = request.headers.get('Authorization')
        if not authorization:
            return False, None

        token = authorization.replace('Bearer ', '')

        if not token:
            return False, None

        user_row = (
            self.query().setRawQuery(
                """
                SELECT users.id_cabang AS id_cabang
                FROM users
                WHERE users.tokens = :token
                """
            )
            .bindparams({'token': token})
            .execute()
            .fetchone()
        )

        user_row = user_row.result if user_row else None

        if not user_row:
            return False, None

        id_cabang = user_row['id_cabang']

        result = (
            self.query().setRawQuery(
                """
                SELECT id_periode FROM periode_closed
                WHERE tanggal_close = :date_now
                AND status = 1
                AND id_cabang = :id_cabang
                """
            )
            .bindparams({'date_now': date_now(), 'id_cabang': id_cabang})
            .execute()
            .fetchone()
        )

        if not result:
            return False, None
        else:
            next_date = date_now_obj() + timedelta(days=1)
            return True, next_date

        print("User row: ", user)


        result = (
            self.query().setRawQuery(
                """
                SELECT id_periode FROM periode_closed
            WHERE  tanggal_close = :date_now
            AND status = 1
                    AND id_cabang = :id_cabang
                """
            )
            .bindparams({'date_now': date_now(), 'id_cabang': user.get('id_cabang')})
            .execute()
            .fetchone()
            .result
        )
        print("Periode closed row: ", result)

        if not result:
            return False, None
        else:
            next_date = date_now_obj() + timedelta(days=1)
            return True, next_date
