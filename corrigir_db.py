import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ponto.db"

def ensure_table_exists(conn, table_name, create_sql):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    exists = cur.fetchone()
    if not exists:
        print(f"⚠️ Tabela '{table_name}' não encontrada. Criando...")
        cur.execute(create_sql)
        conn.commit()
        print(f"✅ Tabela '{table_name}' criada com sucesso.")
    else:
        print(f"✔️ Tabela '{table_name}' já existe.")

def ensure_column_exists(conn, table, column, definition):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if column not in cols:
        print(f"⚠️ Coluna '{column}' ausente na tabela '{table}'. Adicionando...")
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()
        print(f"✅ Coluna '{column}' adicionada em '{table}'.")
    else:
        print(f"✔️ Coluna '{column}' já existe em '{table}'.")

def main():
    if not DB_PATH.exists():
        print("❌ Banco de dados 'ponto.db' não encontrado no diretório atual.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    print(f"🔍 Corrigindo estrutura do banco: {DB_PATH}\n")

    # Garantir tabelas
    ensure_table_exists(conn, "funcionarios", """CREATE TABLE IF NOT EXISTS funcionarios (
        id INTEGER PRIMARY KEY,
        matricula TEXT UNIQUE,
        nome TEXT,
        salario REAL DEFAULT 0,
        banco_horas REAL DEFAULT 0,
        extras_disponiveis INTEGER DEFAULT 0,
        fichado INTEGER DEFAULT 0,
        setor TEXT DEFAULT 'N/D',
        banco_horas_inicial REAL DEFAULT 0,
        extras_disponiveis_inicial INTEGER DEFAULT 0
    )""")

    ensure_table_exists(conn, "horas_trabalhadas", """CREATE TABLE IF NOT EXISTS horas_trabalhadas (
        id INTEGER PRIMARY KEY,
        matricula TEXT,
        data TEXT,
        minutos_totais TEXT,
        periodos TEXT,
        criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(matricula, data)
    )""")

    ensure_table_exists(conn, "log_edicoes", """CREATE TABLE IF NOT EXISTS log_edicoes (
        id INTEGER PRIMARY KEY,
        matricula TEXT,
        data_ponto TEXT,
        data_edicao DATETIME DEFAULT CURRENT_TIMESTAMP,
        periodos_antigos TEXT,
        periodos_novos TEXT,
        justificativa TEXT,
        usuario TEXT DEFAULT 'SYSTEM/MANUAL'
    )""")

    ensure_table_exists(conn, "feriados", """CREATE TABLE IF NOT EXISTS feriados (
        id INTEGER PRIMARY KEY,
        data TEXT UNIQUE,
        descricao TEXT,
        tipo TEXT
    )""")

    ensure_table_exists(conn, "feriados_recorrentes", """CREATE TABLE IF NOT EXISTS feriados_recorrentes (
        id INTEGER PRIMARY KEY,
        dia INTEGER,
        mes INTEGER,
        descricao TEXT,
        tipo TEXT,
        UNIQUE(dia, mes)
    )""")

    ensure_table_exists(conn, "punicoes", """CREATE TABLE IF NOT EXISTS punicoes (
        id INTEGER PRIMARY KEY,
        matricula TEXT,
        data_punicao TEXT,
        minutos_descontados REAL DEFAULT 0,
        motivo TEXT,
        data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (matricula) REFERENCES funcionarios (matricula)
    )""")

    ensure_table_exists(conn, "abonos", """CREATE TABLE IF NOT EXISTS abonos (
        id INTEGER PRIMARY KEY,
        matricula TEXT,
        data TEXT,
        motivo TEXT,
        minutos_abonados REAL DEFAULT 0,
        data_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(matricula, data)
    )""")

    # Garantir colunas principais
    required_columns = {
        "abonos": {
            "matricula": "TEXT",
            "data": "TEXT",
            "motivo": "TEXT",
            "minutos_abonados": "REAL DEFAULT 0",
            "data_registro": "DATETIME DEFAULT CURRENT_TIMESTAMP"
        },
        "funcionarios": {
            "banco_horas_inicial": "REAL DEFAULT 0",
            "extras_disponiveis_inicial": "INTEGER DEFAULT 0"
        },
        "punicoes": {
            "motivo": "TEXT",
            "minutos_descontados": "REAL DEFAULT 0"
        }
    }

    for table, cols in required_columns.items():
        for col, definition in cols.items():
            ensure_column_exists(conn, table, col, definition)

    print("\n✅ Correção concluída com sucesso! Você pode abrir o programa novamente.")
    conn.close()

if __name__ == "__main__":
    main()
