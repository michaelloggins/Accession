import bcrypt
password = "Mv9Br3akGlass2024xAdm1n!"
# Generate bcrypt hash
hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
print(hashed.decode('utf-8'))
