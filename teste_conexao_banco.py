import os
import sqlite3

# Caminho que o seu sistema usa
caminho_sistema = os.path.join(os.getcwd(), "ponto.db")
# Caminho que você viu no DB Browser
caminho_sql = r"C:\Users\washi\Documents\GitHub\wn-ponto-certo-system\ponto.db"

if caminho_sistema.lower() != caminho_sql.lower():
    print(f"ERRO: O sistema está lendo: {caminho_sistema}")
    print(f"Mas você populou: {caminho_sql}")
else:
    print("Caminhos batem. O problema é a função de carregamento UI.")