def test_inicio_requiere_login(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 302
    assert respuesta.url == "/login/?next=/"


def test_login_muestra_formulario(client, db):
    respuesta = client.get("/login/")
    assert respuesta.status_code == 200
    assert "Ingresar" in respuesta.content.decode()
