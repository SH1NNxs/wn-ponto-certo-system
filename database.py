import sqlite3

class Database:
    def __init__(self, db_path='ponto.db'):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS funcionarios (
                id INTEGER PRIMARY KEY,
                nome TEXT NOT NULL UNIQUE
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pontos (
                id INTEGER PRIMARY KEY,
                id_funcionario INTEGER,
                data TEXT,
                entrada TEXT,
                saida TEXT,
                FOREIGN KEY (id_funcionario) REFERENCES funcionarios(id)
            )
        ''')
        self.conn.commit()

    def insert_employee(self, nome):
        try:
            self.cursor.execute("INSERT OR IGNORE INTO funcionarios (nome) VALUES (?)", (nome,))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.Error as e:
            print(f"Erro ao inserir funcionário: {e}")
            return None

    def get_employee_id(self, nome):
        self.cursor.execute("SELECT id FROM funcionarios WHERE nome=?", (nome,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    def insert_punch(self, id_funcionario, data, entrada, saida):
        try:
            self.cursor.execute("INSERT INTO pontos (id_funcionario, data, entrada, saida) VALUES (?, ?, ?, ?)",
                                (id_funcionario, data, entrada, saida))
            self.conn.commit()
        except sqlite3.Error as e:
            print(f"Erro ao inserir ponto: {e}")

    def get_employees(self):
        self.cursor.execute("SELECT * FROM funcionarios")
        return self.cursor.fetchall()
    
    def get_punches_by_date(self, date):
        self.cursor.execute('''
            SELECT f.nome, p.data, p.entrada, p.saida
            FROM pontos p
            JOIN funcionarios f ON p.id_funcionario = f.id
            WHERE p.data = ?
        ''', (date,))
        return self.cursor.fetchall()

    def close(self):
        self.conn.close()