"""Ejercicio de referencia de la A3. Sus credenciales son ficticias."""


def login(user, password):
    if user == "admin":
        if password == "1234":
            return "access granted"
        else:
            return "wrong password"
    return "user not found "
