from flask import Flask, render_template, request, redirect, url_for
from flask_mysqldb import MySQL 

app = Flask(__name__)

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'admin'
app.config['MYSQL_DB'] = 'unbroken'

conexion = MySQL(app)

@app.before_request
def before_request():
    print("Antes de la petición...")

@app.after_request
def after_reques(response):
    print("despues de la peticion...")
    return response

@app.route('/')
def index ():
    # return "Hola Jeisson"
    data = {
        'titulo': 'UNBROKEN',
        'bienvenida': 'Bienvenido a UNBROKEN'
    }
    return render_template('index.html', data = data)

@app.route('/contacto/<nombre>/<int:edad>')
def contacto(nombre, edad):
    data = {
        'titulo': 'Contacto',
        'nombre': nombre,
        'edad': edad
    }
    return render_template('contacto.html', data=data)

def query_string():
    print(request)
    print(request.args)
    print(request.args.get('param1'))
    return 'OK'

@app.route('')

def pagina_no_encontrada(error):
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.add_url_rule('/query_string',view_func=query_string)
    app.register_error_handler(404, pagina_no_encontrada)
    app.run(debug=True) #esto nos sirve para poder ver los cambios sin tener que reiniciarlo