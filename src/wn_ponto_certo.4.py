import os
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
from collections import defaultdict
from datetime import datetime, timedelta, date, time
import sqlite3
import json
from pathlib import Path
from tkcalendar import Calendar
import re
import sys
from PIL import Image as PILImage, ImageTk

# Tenta importar bibliotecas necessárias
try:
    from PIL import Image, ImageTk
except ImportError:
    messagebox.showerror("Biblioteca Faltando", "Pillow: pip install Pillow")
    exit()
try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
except ImportError:
    messagebox.showerror("Biblioteca Faltando", "reportlab: pip install reportlab")
    exit()

# -------------------------
# BANCO DE DADOS (SQLite)
# -------------------------

if getattr(sys, 'frozen', False):
    # Estamos rodando como um .exe (compilado)
    base_path_persistente = Path(sys.executable).parent
    base_path_asset = Path(__file__).parent
else:
    # Estamos rodando como um script .py (desenvolvimento)
    base_path_persistente = Path(__file__).parent
    base_path_asset = Path(__file__).parent

# O Banco de Dados é PERSISTENTE
DEFAULT_DB = base_path_persistente.joinpath("ponto.db")

# O Logo é um ASSET (incluído com --add-data)
LOGO_PATH = base_path_asset.joinpath("wn_logo.png")

# O ÍCONE é um ASSET (também precisa ser incluído)
LOGO_ICON_PATH = base_path_asset.joinpath("wn_logo.ico")

# -------------------------
# CONSTANTES E FUNÇÕES DE APOIO
# -------------------------

# Define a data de início de operação do sistema. Cálculos ignoram datas anteriores.
SYSTEM_START_DATE = "2025-10-20" # <-- Data de início FIXA
# Define a "data atual" para ser usada nos cálculos de recálculo diário.
SYSTEM_CURRENT_DATE = datetime.now().date()


MINUTOS_JORNADA_SEG_SEX = 8 * 60
MINUTOS_JORNADA_SABADO = 4 * 60
MINUTOS_UNIDADE_EXTRA = 4 * 60

LISTA_JUSTIFICATIVAS = ["Ajuste Manual (Erro Batida)", "Início Externo", "Atestado Médico", "Saída Justificada", "Esquecimento Batida"]
LISTA_SETORES = ["Operacional", "Administrativo", "N/D"]
LISTA_FICHADO = ["Sim", "Não"]
LISTA_TIPO_FERIADO = ["Nacional", "Estadual", "Municipal", "Ponto Facultativo"]

def try_parse_datetime(s, format_to_try="%Y-%m-%d %H:%M:%S"):
    try: return datetime.strptime(s, format_to_try)
    except:
        try: return datetime.strptime(s, "%Y/%m/%d %H:%M:%S")
        except:
            try: return datetime.strptime(s, "%Y/%m/%d %H:%M")
            except: return None

# --- FUNÇÃO calculate_deduction ATUALIZADA (NOVAMENTE) ---
def calculate_deduction(minutes_late, sector=None):
    minutes_late = max(0, minutes_late)

    # Regra 1: <= 5 minutos de atraso = 0 desconto
    if minutes_late <= 5:
        return 0

    # Regra 2: Regras específicas por setor
    if sector == "Administrativo":
        if minutes_late <= 15:
            # Atraso * 2
            return minutes_late * 2
        elif minutes_late <= 30:
            # (Primeiros 15 min * 2) + (Excedente * 2) -> Total 60 min para 30 min de atraso
            penalty_first_15 = 15 * 2
            penalty_next_minutes = (minutes_late - 15) * 2
            return penalty_first_15 + penalty_next_minutes
        else: # minutes_late > 30
            # Base de 60 min + (Excedente * 1)
            penalty_first_30 = 60 # (15*2) + (15*2)
            penalty_exceeding = (minutes_late - 30) * 1
            return penalty_first_30 + penalty_exceeding

    elif sector == "Operacional":
        if minutes_late <= 15:
            # Atraso * 3
            return minutes_late * 3
        elif minutes_late <= 30:
            # --- NOVA LÓGICA ESPECÍFICA SOLICITADA ---
            # (Primeiros 15 min * 3) + (Minutos 16 a 30 * 2) -> Total 75 min para 30 min de atraso
            penalty_first_15 = 15 * 3 # 45 minutos
            penalty_next_minutes = (minutes_late - 15) * 2 # Ex: (30-15)*2 = 15*2 = 30 min
            return penalty_first_15 + penalty_next_minutes # Total = 45 + 30 = 75 min
        else: # minutes_late > 30
            # --- NOVA BASE PARA > 30 min ---
            # Base de 75 min (calculada acima para 30 min) + (Excedente * 1)
            penalty_first_30 = 75 # (15*3) + (15*2)
            penalty_exceeding = (minutes_late - 30) * 1
            return penalty_first_30 + penalty_exceeding

    else: # Caso padrão (setor 'N/D' ou None) - Usar regras do Produtivo como default
        if minutes_late <= 15:
            return minutes_late * 3
        elif minutes_late <= 30:
            penalty_first_15 = 15 * 3
            penalty_next_minutes = (minutes_late - 15) * 2 # Multiplicador 2 para 16-30 min
            return penalty_first_15 + penalty_next_minutes
        else:
            penalty_first_30 = 75 # Base 75 min
            penalty_exceeding = (minutes_late - 30) * 1
            return penalty_first_30 + penalty_exceeding
# --- FIM DA FUNÇÃO calculate_deduction ATUALIZADA ---

def format_minutes_to_hms(minutes):
    if minutes is None: return "00:00:00"
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    hours = int(minutes // 60)
    remaining_minutes = int(minutes % 60)
    seconds = int(round((minutes * 60) % 60)) # Arredonda segundos
    if seconds == 60:
        remaining_minutes += 1
        seconds = 0
    if remaining_minutes == 60:
        hours += 1
        remaining_minutes = 0
    return f"{sign}{hours:02}:{remaining_minutes:02}:{seconds:02}"


def parse_hhmm_to_minutes(time_str):
    """Converte uma string HH:MM ou HH:MM:SS para minutos decimais."""
    if not time_str or not re.match(r'^-?\d{1,4}:\d{2}(:\d{2})?$', time_str.strip()):
        return 0

    sign = -1 if time_str.startswith('-') else 1
    time_str = time_str.lstrip('-')

    parts = time_str.split(':')
    minutes = 0
    try:
        if len(parts) == 2:
            h, m = map(int, parts)
            minutes = (h * 60 + m)
        elif len(parts) == 3:
            h, m, s = map(int, parts)
            minutes = (h * 60 + m + s / 60.0)
        return round(minutes * sign, 4)
    except ValueError:
        return 0

# --- Classe DatabaseManager ---
class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = str(db_path if db_path else DEFAULT_DB)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_database()
        self.populate_fixed_holidays()

    def create_database(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS funcionarios (
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
            )
        """)
        c.execute("CREATE TABLE IF NOT EXISTS horas_trabalhadas (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, minutos_totais TEXT, periodos TEXT, criado_em DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        c.execute("CREATE TABLE IF NOT EXISTS log_edicoes (id INTEGER PRIMARY KEY, matricula TEXT, data_ponto TEXT, data_edicao DATETIME DEFAULT CURRENT_TIMESTAMP, periodos_antigos TEXT, periodos_novos TEXT, justificativa TEXT, usuario TEXT DEFAULT 'SYSTEM/MANUAL')")
        c.execute("CREATE TABLE IF NOT EXISTS feriados (id INTEGER PRIMARY KEY, data TEXT UNIQUE, descricao TEXT, tipo TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS feriados_recorrentes (id INTEGER PRIMARY KEY, dia INTEGER, mes INTEGER, descricao TEXT, tipo TEXT, UNIQUE(dia, mes))")
        c.execute("CREATE TABLE IF NOT EXISTS punicoes (id INTEGER PRIMARY KEY, matricula TEXT, data_punicao TEXT, minutos_descontados REAL DEFAULT 0, motivo TEXT, data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (matricula) REFERENCES funcionarios (matricula))")
        c.execute("CREATE TABLE IF NOT EXISTS abonos (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, motivo TEXT, minutos_abonados REAL DEFAULT 0, data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        c.execute("CREATE TABLE IF NOT EXISTS abonos (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, motivo TEXT, minutos_abonados REAL DEFAULT 0, data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        self.conn.commit()

    def populate_fixed_holidays(self):
        fixed_holidays = [
            (1, 1, 'Confraternização Universal', 'Nacional'),
            (6, 3, 'Data Magna PE', 'Estadual'),
            (21, 4, 'Tiradentes', 'Nacional'),
            (1, 5, 'Dia Trabalhador', 'Nacional'),
            (24, 6, 'São João', 'Estadual'),
            (7, 9, 'Independência BR', 'Nacional'),
            (12, 10, 'N Sra Aparecida', 'Nacional'),
            (2, 11, 'Finados', 'Nacional'),
            (15, 11, 'Proclamação República', 'Nacional'),
            (25, 12, 'Natal', 'Nacional')
        ]
        try:
            c = self.conn.cursor()
            query = "INSERT OR IGNORE INTO feriados_recorrentes (dia, mes, descricao, tipo) VALUES (?, ?, ?, ?)"
            [c.execute(query, h) for h in fixed_holidays]
            self.conn.commit()
        except Exception as e:
            print(f"Erro feriados recorrentes: {e}")

    def add_holiday(self, date_str, descricao, tipo):
        try:
            self.conn.execute("INSERT OR REPLACE INTO feriados (data, descricao, tipo) VALUES (?, ?, ?)", (date_str, descricao, tipo))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro add feriado específico: {e}")
            return False

    def add_recurring_holiday(self, dia, mes, descricao, tipo):
        try:
            self.conn.execute("INSERT OR REPLACE INTO feriados_recorrentes (dia, mes, descricao, tipo) VALUES (?, ?, ?, ?)", (dia, mes, descricao, tipo))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro add feriado recorrente: {e}")
            return False

    def get_all_specific_holidays(self):
        c = self.conn.cursor()
        c.execute("SELECT id, data, descricao, tipo FROM feriados WHERE data >= ? ORDER BY data", (SYSTEM_START_DATE,))
        return [dict(row) for row in c.fetchall()]

    def get_all_recurring_holidays(self):
        c = self.conn.cursor()
        c.execute("SELECT id, dia, mes, descricao, tipo FROM feriados_recorrentes ORDER BY mes, dia")
        return [dict(row) for row in c.fetchall()]

    def delete_specific_holiday(self, holiday_id):
        try:
            self.conn.execute("DELETE FROM feriados WHERE id = ?", (holiday_id,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao deletar feriado específico: {e}")
            return False

    def delete_recurring_holiday(self, holiday_id):
        try:
            self.conn.execute("DELETE FROM feriados_recorrentes WHERE id = ?", (holiday_id,))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro ao deletar feriado recorrente: {e}")
            return False

    def get_holidays_for_month(self, year, month):
        c = self.conn.cursor()
        holiday_dates = set()

        query_spec = "SELECT data FROM feriados WHERE strftime('%Y-%m', data) = ?"
        target_month = f"{year:04}-{month:02}"
        c.execute(query_spec, (target_month,))
        [holiday_dates.add(datetime.strptime(row['data'], '%Y-%m-%d').date()) for row in c.fetchall() if row['data']]

        query_rec = "SELECT dia FROM feriados_recorrentes WHERE mes = ?"
        c.execute(query_rec, (month,))
        for row in c.fetchall():
            if row['dia']:
                try:
                    holiday_dates.add(date(year, month, row['dia']))
                except ValueError:
                    pass

        return holiday_dates


    def get_holidays_in_range(self, start_date, end_date):
        c = self.conn.cursor()
        all_holidays = []

        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date
        query_spec = "SELECT data, descricao, tipo FROM feriados WHERE data BETWEEN ? AND ? AND data >= ? ORDER BY data"
        c.execute(query_spec, (start_date_str, end_date_str, SYSTEM_START_DATE))
        all_holidays = [dict(row) for row in c.fetchall()]

        query_rec = "SELECT dia, mes, descricao, tipo FROM feriados_recorrentes"
        recurring = c.execute(query_rec).fetchall()

        if recurring:
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

            current_date_iter = start_date
            while current_date_iter <= end_date:
                for rec in recurring:
                    if current_date_iter.day == rec['dia'] and current_date_iter.month == rec['mes']:
                        if not any(h['data'] == current_date_iter.isoformat() for h in all_holidays):
                            all_holidays.append({
                                'data': current_date_iter.isoformat(),
                                'descricao': rec['descricao'],
                                'tipo': rec['tipo']
                            })
                current_date_iter += timedelta(days=1)

        all_holidays.sort(key=lambda x: x['data'])
        return all_holidays

    def add_punicao(self, matricula, data_punicao_str, minutos_descontados, motivo):
        try:
            with self.conn:
                self.conn.execute("INSERT INTO punicoes (matricula, data_punicao, minutos_descontados, motivo) VALUES (?, ?, ?, ?)", (matricula, data_punicao_str, minutos_descontados, motivo))
                self.log_edicao(matricula, data_punicao_str, "Punição: 0 min", f"Punição: {format_minutes_to_hms(minutos_descontados)}", f"Punição: {motivo}")
            return True
        except Exception as e:
            print(f"Erro add punição: {e}")
            return False


    def get_total_punishment_minutes_for_day(self, matricula, date_str):
        c = self.conn.cursor()
        query = "SELECT SUM(minutos_descontados) as total FROM punicoes WHERE matricula = ? AND data_punicao = ?"
        c.execute(query, (matricula, date_str))
        result = c.fetchone()
        return result['total'] if result and result['total'] is not None else 0

    def get_punishments_in_range(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date
        query = "SELECT data_punicao, minutos_descontados, motivo FROM punicoes WHERE matricula = ? AND data_punicao BETWEEN ? AND ? AND data_punicao >= ? ORDER BY data_punicao"
        c.execute(query, (matricula, start_date_str, end_date_str, SYSTEM_START_DATE))
        return [dict(row) for row in c.fetchall()]
    
    def add_abono(self, matricula, data_abono_str, motivo, minutos_abonados):
        try:
            with self.conn:
                self.conn.execute("INSERT OR REPLACE INTO abonos (matricula, data, motivo, minutos_abonados) VALUES (?, ?, ?, ?)", (matricula, data_abono_str, motivo, minutos_abonados))
                self.log_edicao(matricula, data_abono_str, "Abono: 00:00:00", f"Abono: {format_minutes_to_hms(minutos_abonados)}", f"Abono: {motivo}")
            return True
        except Exception as e:
            print(f"Erro add abono: {e}")
            return False

    def delete_abono(self, abono_id):
        try:
            with self.conn:
                # Precisamos pegar os dados antes de deletar para logar
                c = self.conn.cursor()
                c.execute("SELECT matricula, data, motivo, minutos_abonados FROM abonos WHERE id = ?", (abono_id,))
                row = c.fetchone()
                if row:
                    minutos_str = format_minutes_to_hms(row.get('minutos_abonados', 0))
                    self.conn.execute("DELETE FROM abonos WHERE id = ?", (abono_id,))
                    self.log_edicao(row['matricula'], row['data'], f"Abono: {minutos_str} ({row['motivo']})", "Abono: Removido", "Remoção de Abono")
                    return row['matricula'] # Retorna a matrícula para recalcular
            return False
        except Exception as e:
            print(f"Erro delete abono: {e}")
            return False
            
    def get_abonos_in_range(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date
        query = "SELECT id, data, motivo, minutos_abonados FROM abonos WHERE matricula = ? AND data BETWEEN ? AND ? AND data >= ? ORDER BY data"
        c.execute(query, (matricula, start_date_str, end_date_str, SYSTEM_START_DATE))
        return [dict(row) for row in c.fetchall()]

    def get_abono_minutes_for_day(self, matricula, date_str):
        c = self.conn.cursor()
        query = "SELECT minutos_abonados FROM abonos WHERE matricula = ? AND data = ?"
        c.execute(query, (matricula, date_str))
        result = c.fetchone()
        return result['minutos_abonados'] if result and result['minutos_abonados'] is not None else 0

    # --- NOVO MÉTODO: get_stats_for_period ---
    def get_stats_for_period(self, matricula, start_date, end_date):
        """Coleta estatísticas de faltas, atrasos e punições para um período."""
        c = self.conn.cursor()
        
        try:
            func_info = self.get_funcionario_info(matricula)
            is_fichado = func_info.get('fichado', 0) == 1
        except Exception:
            is_fichado = False # Padrão
            
        start_date_obj = start_date if isinstance(start_date, date) else datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date_obj = end_date if isinstance(end_date, date) else datetime.strptime(end_date, '%Y-%m-%d').date()
        
        stats = {
            'total_absences': 0,
            'partial_absences': 0,
            'days_with_delay': 0,
            'total_delay_discount': 0.0,
            'punishment_count': 0,
            'total_punishment_discount': 0.0
        }

        # 1. Coletar Punições
        punishments = self.get_punishments_in_range(matricula, start_date_obj, end_date_obj)
        stats['punishment_count'] = len(punishments)
        stats['total_punishment_discount'] = sum(p.get('minutos_descontados', 0) for p in punishments)

        # 2. Iterar dias para Faltas e Atrasos
        current_date_iter = start_date_obj
        while current_date_iter <= end_date_obj:
            date_str = current_date_iter.isoformat()
            
            # Pega a expectativa de trabalho
            expected_minutes = self.get_expected_daily_minutes(date_str, is_fichado)

            # Pega o trabalho realizado
            c.execute("SELECT periodos, minutos_totais FROM horas_trabalhadas WHERE matricula=? AND data=?", (matricula, date_str))
            row = c.fetchone()
            
            worked_minutes = parse_hhmm_to_minutes(row['minutos_totais']) if row and row['minutos_totais'] else 0
            day_delay_discount = 0

            if row and row['periodos']:
                try:
                    periods_json = json.loads(row['periodos'])
                    for p in periods_json:
                        delay_min = parse_hhmm_to_minutes(p.get('deducao_minutos', '00:00:00'))
                        if delay_min > 0:
                            day_delay_discount += delay_min
                except:
                    pass # Ignora erros de JSON

            if day_delay_discount > 0:
                stats['days_with_delay'] += 1
                stats['total_delay_discount'] += day_delay_discount

            # Contabiliza Faltas
            if expected_minutes > 0:
                if worked_minutes == 0:
                    stats['total_absences'] += 1
                elif worked_minutes < expected_minutes:
                    stats['partial_absences'] += 1
            
            current_date_iter += timedelta(days=1)
            
        return stats
    # --- FIM DO NOVO MÉTODO ---

    def is_holiday(self, date_str):
        try:
            c = self.conn.cursor()

            c.execute("SELECT 1 FROM feriados WHERE data = ?", (date_str,))
            if c.fetchone():
                return True

            try:
                date_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                c.execute("SELECT 1 FROM feriados_recorrentes WHERE dia = ? AND mes = ?", (date_dt.day, date_dt.month))
                if c.fetchone():
                    return True
            except ValueError:
                return False

            return False
        
        except Exception as e:
            print(f"Erro ao checar feriado para {date_str}: {e}")
            return False

    def get_expected_daily_minutes(self, date_str, is_fichado, matricula):
        # --- ADICIONE ESTA LINHA ---
        print(f"DEBUG: Dentro de get_expected_daily_minutes, recebido date_str = {date_str}")
    # --- FIM DA ADIÇÃO ---
        """Retorna a carga horária esperada (débito) para um dia."""
        try:
            date_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return 0

        # 1. Domingo sempre tem 0 horas esperadas para todos.
        if date_dt.weekday() == 6:
            return 0

        # 2. Verifica se é feriado.
        is_holiday_today = self.is_holiday(date_str) # Chamada corrigida

        # 3. Se for feriado E o funcionário for FICHADO, a expectativa é 0.
        #    Para NÃO FICHADO, o feriado é tratado como dia normal (a função continua).
        if is_holiday_today and is_fichado:
            return 0
            
        # 4. Calcula a expectativa normal
        normal_expected_minutes = 0
        if date_dt.weekday() < 5: # Seg-Sex
            normal_expected_minutes = MINUTOS_JORNADA_SEG_SEX
        elif date_dt.weekday() == 5: # Sab
            normal_expected_minutes = MINUTOS_JORNADA_SABADO
        
        # 5. Aplica Abono Parcial (se houver)
        if matricula:
            abono_minutos = self.get_abono_minutes_for_day(matricula, date_str)
            return max(0, normal_expected_minutes - abono_minutos)
        
        return normal_expected_minutes # Retorna normal se matricula for None

    def insert_funcionario(self, dados):
        bh_inicial = dados.get("banco_horas_inicial", 0)
        extras_inicial = dados.get("extras_disponiveis_inicial", 0)
        bh_corrente = dados.get("banco_horas", bh_inicial)
        extras_corrente = dados.get("extras_disponiveis", extras_inicial)

        query = """
            INSERT OR IGNORE INTO funcionarios
            (matricula, nome, fichado, setor, banco_horas, extras_disponiveis, banco_horas_inicial, extras_disponiveis_inicial)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.conn.execute(query, (
            dados.get("matricula"),
            dados.get("nome"),
            dados.get("fichado", 0),
            dados.get("setor", "N/D"),
            bh_corrente,
            extras_corrente,
            bh_inicial,
            extras_inicial
        ))
        self.conn.commit()

    def insert_horas_trabalhadas(self, dados, justificativa="Importação Automática"):
        cur = self.conn.cursor()
        cur.execute("SELECT periodos FROM horas_trabalhadas WHERE matricula=? AND data=?", (dados.get("matricula"), dados.get("data")))
        old_data = cur.fetchone()
        periodos_antigos = old_data['periodos'] if old_data else "[]"
        self.conn.execute("INSERT OR REPLACE INTO horas_trabalhadas (matricula, data, minutos_totais, periodos) VALUES (?, ?, ?, ?)", (dados.get("matricula"), dados.get("data"), dados.get("minutos_totais"), json.dumps(dados.get("periodos"), default=str)))
        self.conn.commit()
        if justificativa != "Importação Automática" or old_data:
            self.log_edicao(dados.get("matricula"), dados.get("data"), periodos_antigos, json.dumps(dados.get("periodos"), default=str), justificativa)

    def log_edicao(self, matricula, data_ponto, periodos_antigos, periodos_novos, justificativa):
        self.conn.execute("INSERT INTO log_edicoes (matricula, data_ponto, periodos_antigos, periodos_novos, justificativa) VALUES (?, ?, ?, ?, ?)", (matricula, data_ponto, periodos_antigos, periodos_novos, justificativa))
        self.conn.commit()

    def get_funcionario_info(self, matricula):
        c = self.conn.cursor()
        c.execute("SELECT * FROM funcionarios WHERE matricula = ?", (matricula,))
        return dict(c.fetchone() or {})

    def get_all_funcionarios(self):
        c = self.conn.cursor()
        c.execute("SELECT matricula, nome FROM funcionarios ORDER BY nome")
        return [dict(row) for row in c.fetchall()]

    def get_all_employees_with_details(self):
        c = self.conn.cursor()
        c.execute("SELECT matricula, nome, fichado, setor FROM funcionarios ORDER BY nome")
        return [dict(row) for row in c.fetchall()]

    def get_all_funcionarios_matriculas(self):
        c = self.conn.cursor()
        c.execute("SELECT matricula FROM funcionarios")
        return {row['matricula'] for row in c.fetchall()}

    def update_employee_details(self, matricula, fichado, setor):
        try:
            info_antes = self.get_funcionario_info(matricula)
            periodo_antigo = f"Fichado: {info_antes.get('fichado', 0)}, Setor: {info_antes.get('setor', 'N/D')}"
            periodo_novo = f"Fichado: {fichado}, Setor: {setor}"
            self.conn.execute("UPDATE funcionarios SET fichado = ?, setor = ? WHERE matricula = ?", (fichado, setor, matricula))
            self.conn.commit()
            self.log_edicao(matricula, datetime.now().strftime("%Y-%m-%d"), periodo_antigo, periodo_novo, "Alteração Cadastral")
            return True
        except Exception as e:
            print(f"Erro update func: {e}")
            return False

    def get_logs_for_period(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date
        query = """
            SELECT l.data_ponto, l.data_edicao, l.periodos_antigos, l.periodos_novos, l.justificativa, f.nome
            FROM log_edicoes l JOIN funcionarios f ON l.matricula = f.matricula
            WHERE l.matricula = ?
              AND l.data_ponto BETWEEN ? AND ?
              AND l.data_ponto >= ?
            ORDER BY l.data_ponto, l.data_edicao
        """
        c.execute(query, (matricula, start_date_str, end_date_str, SYSTEM_START_DATE))
        return [dict(row) for row in c.fetchall()]

    def _get_daily_summary_for_display(self, matricula, date_str):
        c = self.conn.cursor()
        c.execute("SELECT minutos_totais, periodos FROM horas_trabalhadas WHERE matricula=? AND data=?", (matricula, date_str))
        row = c.fetchone()
        if not row: return "00:00:00", "00:00:00"
        total_worked = row['minutos_totais']
        total_delay_penalty_minutes = 0 # Precisamos do total de penalidade, não só atraso
        try:
            periods_json = json.loads(row['periodos']) if row['periodos'] else []
            for p in periods_json:
                # O valor que queremos mostrar como "Total Desconto" é a penalidade calculada
                total_delay_penalty_minutes += parse_hhmm_to_minutes(p.get('deducao_minutos', '00:00:00'))
        except Exception as e:
             print(f"Erro ao calcular dedução display para {matricula} em {date_str}: {e}")
             pass
        # Retorna o total líquido trabalhado e o total de penalidade
        return total_worked, format_minutes_to_hms(total_delay_penalty_minutes)


    def get_point_panorama(self, start_date, end_date, target_matricula=None):
        if not start_date or not end_date: return []
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date
        if target_matricula and target_matricula != 'Todos':
            funcionarios = [self.get_funcionario_info(target_matricula)]
        else:
            funcionarios = self.get_all_funcionarios()
        if not funcionarios or not any(f for f in funcionarios if f): return []
        try:
            start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError: return []

        matriculas_list = [f['matricula'] for f in funcionarios if f]
        if not matriculas_list: return []

        c = self.conn.cursor()
        placeholders = ','.join('?' for _ in matriculas_list)

        sql_todos_horas = f"""
            SELECT matricula, data, periodos, minutos_totais
            FROM horas_trabalhadas
            WHERE matricula IN ({placeholders}) AND data >= ?
            ORDER BY data ASC
        """
        params = matriculas_list + [SYSTEM_START_DATE]
        c.execute(sql_todos_horas, params)
        todos_os_dados_historicos = c.fetchall()

        panorama_final = []
        start_sim_dt = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()

        for func_base in funcionarios:
            if not func_base: continue
            matricula = func_base['matricula']
            info_final_real = self.get_funcionario_info(matricula)
            is_fichado = info_final_real.get('fichado', 0) == 1

            work_map = {}
            dados_func = [r for r in todos_os_dados_historicos if r['matricula'] == matricula]
            for row in dados_func:
                minutos_trabalhados = parse_hhmm_to_minutes(row['minutos_totais'])
                work_map[row['data']] = {'minutos': minutos_trabalhados, 'periodos': row['periodos']}

            saldo_bh_simulado = info_final_real.get('banco_horas_inicial', 0)
            saldo_extras_simulado = info_final_real.get('extras_disponiveis_inicial', 0)
            historico_simulado = {}

            current_sim_iter = start_sim_dt
            
            yesterday = SYSTEM_CURRENT_DATE - timedelta(days=1)
            sim_end_dt = max(end_dt, yesterday) # Simula até o fim do período ou ontem

            while current_sim_iter <= sim_end_dt:
                date_str = current_sim_iter.isoformat() # Variável usada dentro do loop
                bh_anterior_simulado = saldo_bh_simulado
                extras_anterior_simulado = saldo_extras_simulado

                if current_sim_iter == SYSTEM_CURRENT_DATE:
                    historico_simulado[date_str] = {
                        'bh_anterior': bh_anterior_simulado,
                        'bh_saldo': saldo_bh_simulado, # Saldo final de ontem
                        'extras_anterior': extras_anterior_simulado,
                        'extras_saldo': saldo_extras_simulado # Saldo final de ontem
                    }
                    current_sim_iter += timedelta(days=1)
                    continue # Pula o resto do cálculo

                print(f"DEBUG: Antes de chamar get_expected_daily_minutes para {matricula} em {date_str}")

                expected_minutes = self.get_expected_daily_minutes(date_str, is_fichado, matricula)

                minutos_trabalhados_dia = work_map.get(date_str, {}).get('minutos', 0)
                excedente_dia = minutos_trabalhados_dia - expected_minutes
                saldo_bh_simulado += excedente_dia

                while saldo_bh_simulado >= MINUTOS_UNIDADE_EXTRA:
                    saldo_bh_simulado -= MINUTOS_UNIDADE_EXTRA
                    saldo_extras_simulado += 1
                while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                    saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                    saldo_extras_simulado -= 1

                punicao_do_dia = self.get_total_punishment_minutes_for_day(matricula, date_str)
                if punicao_do_dia > 0:
                    saldo_bh_simulado -= punicao_do_dia
                    while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                        saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                        saldo_extras_simulado -= 1

                historico_simulado[date_str] = {
                    'bh_anterior': bh_anterior_simulado,
                    'bh_saldo': saldo_bh_simulado,
                    'extras_anterior': extras_anterior_simulado,
                    'extras_saldo': saldo_extras_simulado
                }
                current_sim_iter += timedelta(days=1)

            current_date_iter = start_dt
            while current_date_iter <= end_dt:
                date_str = current_date_iter.isoformat() # Variável usada dentro do loop

                dados_do_dia = work_map.get(date_str)
                simulacao_do_dia = historico_simulado.get(date_str)

                if not simulacao_do_dia:
                    if current_date_iter < start_sim_dt:
                        simulacao_do_dia = {
                            'bh_anterior': info_final_real.get('banco_horas_inicial', 0),
                            'bh_saldo': info_final_real.get('banco_horas_inicial', 0),
                            'extras_anterior': info_final_real.get('extras_disponiveis_inicial', 0),
                            'extras_saldo': info_final_real.get('extras_disponiveis_inicial', 0)
                        }
                    else:
                        last_sim_date = max((d for d in historico_simulado if d < date_str), default=None)
                        if last_sim_date:
                            simulacao_do_dia = {
                                'bh_anterior': historico_simulado[last_sim_date]['bh_saldo'],
                                'bh_saldo': historico_simulado[last_sim_date]['bh_saldo'],
                                'extras_anterior': historico_simulado[last_sim_date]['extras_saldo'],
                                'extras_saldo': historico_simulado[last_sim_date]['extras_saldo']
                            }
                        else:
                            simulacao_do_dia = {
                                'bh_anterior': info_final_real.get('banco_horas_inicial', 0),
                                'bh_saldo': info_final_real.get('banco_horas_inicial', 0),
                                'extras_anterior': info_final_real.get('extras_disponiveis_inicial', 0),
                                'extras_saldo': info_final_real.get('extras_disponiveis_inicial', 0)
                            }

                carga_horaria_dia_str, total_desconto_penalidade_str, horarios = "00:00:00", "00:00:00", []
                is_incomplete_day = False

                if dados_do_dia:
                    carga_horaria_dia_str_temp, total_desconto_penalidade_str_temp = self._get_daily_summary_for_display(matricula, date_str)
                    carga_horaria_dia_str = carga_horaria_dia_str_temp
                    total_desconto_penalidade_str = total_desconto_penalidade_str_temp

                    try:
                        periods_json = json.loads(dados_do_dia['periodos']) if dados_do_dia['periodos'] else []
                        for p in periods_json:
                             entrada_str = p.get('entrada')
                             saida_str = p.get('saida')
                             if entrada_str:
                                 horarios.append(datetime.strptime(entrada_str, '%Y-%m-%d %H:%M:%S').strftime('%H:%M'))
                             if saida_str:
                                 horarios.append(datetime.strptime(saida_str, '%Y-%m-%d %H:%M:%S').strftime('%H:%M'))
                             if entrada_str and not saida_str:
                                 is_incomplete_day = True
                    except Exception as e:
                        print(f"Erro ao processar períodos para {matricula} em {date_str}: {e}")
                        pass

                ponto_dict = {
                    'Matricula': matricula, 'Nome': info_final_real['nome'], 'Data': date_str,
                    'E1': '', 'S1': '', 'E2': '', 'S2': '',
                    'Carga_Horaria': carga_horaria_dia_str, 
                    'Total_Desconto': total_desconto_penalidade_str,
                    'BH_Anterior': format_minutes_to_hms(simulacao_do_dia['bh_anterior']),
                    'BH_Saldo': format_minutes_to_hms(simulacao_do_dia['bh_saldo']),
                    'Extras_Disp': str(int(simulacao_do_dia['extras_saldo'])),
                    'is_incomplete': is_incomplete_day
                }

                if len(horarios) >= 1: ponto_dict['E1'] = horarios[0]
                if len(horarios) >= 2: ponto_dict['S1'] = horarios[1]
                if len(horarios) >= 3: ponto_dict['E2'] = horarios[2]
                if len(horarios) >= 4: ponto_dict['S2'] = horarios[3]
                panorama_final.append(ponto_dict)

                current_date_iter += timedelta(days=1)

        panorama_final.sort(key=lambda x: (x['Nome'], x['Data']))
        return panorama_final
    
    def get_worked_days_in_range(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date

        query = """
            SELECT data
            FROM horas_trabalhadas
            WHERE matricula = ?
              AND data BETWEEN ? AND ?
              AND data >= ?
              AND minutos_totais IS NOT NULL
              AND minutos_totais != '00:00:00'
            ORDER BY data
        """
        c.execute(query, (matricula, start_date_str, end_date_str, SYSTEM_START_DATE))

        worked_dates = []
        for row in c.fetchall():
            try:
                worked_dates.append(datetime.strptime(row['data'], '%Y-%m-%d').date())
            except:
                continue
        return worked_dates

    def update_saldos(self, matricula, minutos_a_deduzir_bh, unidades_a_deduzir_extras):
        try:
            info_antes = self.get_funcionario_info(matricula)
            saldo_bh_antes = info_antes.get('banco_horas', 0)
            saldo_extras_antes = info_antes.get('extras_disponiveis', 0)

            novo_saldo_bh = saldo_bh_antes - minutos_a_deduzir_bh
            novo_saldo_extras = saldo_extras_antes - unidades_a_deduzir_extras

            self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (novo_saldo_bh, novo_saldo_extras, matricula))
            self.conn.commit()

            data_hoje = datetime.now().strftime("%Y-%m-%d")
            justificativa = "Pagamento/Dedução Saldo"
            periodo_antigo = f"BH: {format_minutes_to_hms(saldo_bh_antes)}, Extras: {int(saldo_extras_antes)}"
            periodo_novo = f"BH: {format_minutes_to_hms(novo_saldo_bh)}, Extras: {int(novo_saldo_extras)}"
            self.log_edicao(matricula, data_hoje, periodo_antigo, periodo_novo, justificativa)

            return True
        except Exception as e:
            print(f"Erro update saldos: {e}")
            return False
    
    def update_initial_balances(self, matricula, new_bh_inicial, new_extras_inicial):
        try:
            info_antes = self.get_funcionario_info(matricula)
            saldo_bh_antes = info_antes.get('banco_horas_inicial', 0)
            saldo_extras_antes = info_antes.get('extras_disponiveis_inicial', 0)

            with self.conn:
                self.conn.execute("UPDATE funcionarios SET banco_horas_inicial = ?, extras_disponiveis_inicial = ? WHERE matricula = ?", (new_bh_inicial, new_extras_inicial, matricula))

            data_hoje = datetime.now().strftime("%Y-%m-%d")
            justificativa = "Ajuste Saldo Inicial"
            periodo_antigo = f"BH Inicial: {format_minutes_to_hms(saldo_bh_antes)}, Extras Iniciais: {int(saldo_extras_antes)}"
            periodo_novo = f"BH Inicial: {format_minutes_to_hms(new_bh_inicial)}, Extras Iniciais: {int(new_extras_inicial)}"
            self.log_edicao(matricula, data_hoje, periodo_antigo, periodo_novo, justificativa)
            
            return True
        except Exception as e:
            print(f"Erro update saldos iniciais: {e}")
            return False


    def recalculate_full_balance_for_employee(self, matricula):
        c = self.conn.cursor()
        func_info = self.get_funcionario_info(matricula)
        # Se funcionário não for encontrado, não faz nada
        if not func_info:
             print(f"AVISO: Funcionário com matrícula {matricula} não encontrado para recálculo.")
             return

        is_fichado = func_info.get('fichado', 0) == 1

        saldo_bh_minutos = func_info.get('banco_horas_inicial', 0)
        saldo_extras = func_info.get('extras_disponiveis_inicial', 0)

        c.execute("SELECT data, minutos_totais FROM horas_trabalhadas WHERE matricula = ? AND data >= ? ORDER BY data ASC", (matricula, SYSTEM_START_DATE))
        all_work_days = c.fetchall()

        work_map = {}
        for day in all_work_days:
            minutos_trabalhados = parse_hhmm_to_minutes(day['minutos_totais'])
            work_map[day['data']] = minutos_trabalhados

        try:
            start_dt = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
            # --- MODIFICAÇÃO (Não calcular dia de hoje) ---
            # O recálculo oficial só vai até ONTEM.
            end_dt = SYSTEM_CURRENT_DATE - timedelta(days=1)
            # --- FIM DA MODIFICAÇÃO ---
        except ValueError:
            print(f"Erro ao parsear datas de início/fim em recalculate para {matricula}")
            return

        if start_dt > end_dt:
             self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (saldo_bh_minutos, saldo_extras, matricula))
             self.conn.commit()
             return

        current_date_iter = start_dt
        while current_date_iter <= end_dt:
            date_str = current_date_iter.isoformat()

            expected_minutes = self.get_expected_daily_minutes(date_str, is_fichado, matricula) # Chama a função corrigida

            minutos_trabalhados_dia = work_map.get(date_str, 0)
            excedente_dia = minutos_trabalhados_dia - expected_minutes
            saldo_bh_minutos += excedente_dia

            while saldo_bh_minutos >= MINUTOS_UNIDADE_EXTRA:
                saldo_bh_minutos -= MINUTOS_UNIDADE_EXTRA
                saldo_extras += 1
            while saldo_bh_minutos < 0 and saldo_extras > 0:
                saldo_bh_minutos += MINUTOS_UNIDADE_EXTRA
                saldo_extras -= 1

            current_date_iter += timedelta(days=1)

        c.execute("SELECT SUM(minutos_descontados) as total_punicao FROM punicoes WHERE matricula = ? AND data_punicao >= ?", (matricula, SYSTEM_START_DATE))
        punicao_total = c.fetchone()['total_punicao'] or 0
        saldo_bh_minutos -= punicao_total
        while saldo_bh_minutos < 0 and saldo_extras > 0:
             saldo_bh_minutos += MINUTOS_UNIDADE_EXTRA
             saldo_extras -= 1


        c.execute("SELECT periodos_antigos, periodos_novos FROM log_edicoes WHERE matricula = ? AND justificativa = 'Pagamento/Dedução Saldo' AND data_ponto >= ?", (matricula, SYSTEM_START_DATE))
        logs_pagamento = c.fetchall()

        total_extras_pagos = 0
        total_bh_pagos = 0 # (Não implementado, mas para futuro)

        for log in logs_pagamento:
            try:
                antigo_str = log['periodos_antigos']
                novo_str = log['periodos_novos']

                # Extrai "Extras: X"
                extras_antigo_match = re.search(r'Extras: (\-?\d+)', antigo_str)
                extras_novo_match = re.search(r'Extras: (\-?\d+)', novo_str)

                if extras_antigo_match and extras_novo_match:
                    extras_antigo = int(extras_antigo_match.group(1))
                    extras_novo = int(extras_novo_match.group(1))
                    total_extras_pagos += (extras_antigo - extras_novo)

            except Exception as e:
                print(f"Erro ao parsear log de pagamento para recálculo: {e}")

        saldo_extras -= total_extras_pagos

        while saldo_extras < 0:
             saldo_extras += 1
             saldo_bh_minutos -= MINUTOS_UNIDADE_EXTRA

        self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (saldo_bh_minutos, saldo_extras, matricula))
        self.conn.commit()
    
    def get_detailed_stats_for_period(self, matricula, start_date, end_date):
        """Gera estatísticas detalhadas simulando o período."""
        
        func_info = self.get_funcionario_info(matricula)
        if not func_info:
            raise Exception(f"Funcionário {matricula} não encontrado.")
            
        is_fichado = func_info.get('fichado', 0) == 1
        
        stats = {
            'matricula': matricula,
            'nome': func_info.get('nome', 'N/D'),
            'start_date': start_date,
            'end_date': end_date,
            'dias_trabalhados': 0,
            'faltas_abonadas': 0,
            'faltas_nao_abonadas': 0,
            'minutos_abonados_total': 0, # <-- NOVO CAMPO
            'punicoes_min': 0,
            'punicoes_count': 0,
            'atrasos_deduzidos_min': 0,
            'dias_com_atraso': 0,
            'bh_start': 0,
            'bh_end': 0,
            'extras_start': 0,
            'extras_end': 0,
            'extras_geradas_periodo': 0
        }

        c = self.conn.cursor()
        
        # 1. Coleta todos os dados relevantes de uma vez
        c.execute("SELECT data, minutos_totais, periodos FROM horas_trabalhadas WHERE matricula = ? AND data >= ? AND data <= ? ORDER BY data ASC", (matricula, SYSTEM_START_DATE, end_date.isoformat()))
        all_work_days = c.fetchall()
        work_map = {row['data']: {'minutos': parse_hhmm_to_minutes(row['minutos_totais']), 'periodos': row['periodos']} for row in all_work_days}
        
        punicoes = self.get_punishments_in_range(matricula, SYSTEM_START_DATE, end_date)
        punicoes_map = {p['data_punicao']: p['minutos_descontados'] for p in punicoes}
        
        # Agora pega o mapa de minutos
        abonos = self.get_abonos_in_range(matricula, SYSTEM_START_DATE, end_date)
        abonos_map = {a['data']: a.get('minutos_abonados', 0) for a in abonos}

        # 2. Simula do início do sistema ATÉ o início do relatório (para pegar saldos iniciais)
        saldo_bh_simulado = func_info.get('banco_horas_inicial', 0)
        saldo_extras_simulado = func_info.get('extras_disponiveis_inicial', 0)
        
        sim_start_dt = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        sim_end_dt = start_date - timedelta(days=1) # Simula ATÉ a véspera
        current_sim_iter = sim_start_dt
        
        if sim_start_dt <= sim_end_dt:
            while current_sim_iter <= sim_end_dt:
                date_str = current_sim_iter.isoformat()
                
                if current_sim_iter == SYSTEM_CURRENT_DATE:
                    current_sim_iter += timedelta(days=1)
                    continue
                
                expected_minutes = self.get_expected_daily_minutes(date_str, is_fichado, matricula)
                minutos_trabalhados_dia = work_map.get(date_str, {}).get('minutos', 0)
                excedente_dia = minutos_trabalhados_dia - expected_minutes
                saldo_bh_simulado += excedente_dia

                while saldo_bh_simulado >= MINUTOS_UNIDADE_EXTRA:
                    saldo_bh_simulado -= MINUTOS_UNIDADE_EXTRA
                    saldo_extras_simulado += 1
                while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                    saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                    saldo_extras_simulado -= 1

                punicao_do_dia = punicoes_map.get(date_str, 0)
                if punicao_do_dia > 0:
                    saldo_bh_simulado -= punicao_do_dia
                    while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                        saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                        saldo_extras_simulado -= 1
                        
                current_sim_iter += timedelta(days=1)
        
        stats['bh_start'] = saldo_bh_simulado
        stats['extras_start'] = saldo_extras_simulado

        # 3. Simula DENTRO do período do relatório (para pegar estatísticas e saldos finais)
        current_date_iter = start_date
        while current_date_iter <= end_date:
            date_str = current_date_iter.isoformat()
            
            if current_date_iter == SYSTEM_CURRENT_DATE:
                 current_date_iter += timedelta(days=1)
                 continue

            # Pega expectativa (já com abono subtraído)
            expected_minutes = self.get_expected_daily_minutes(date_str, is_fichado, matricula)
            
            # Pega expectativa (sem abono) para contagem de faltas
            date_dt = current_date_iter
            expected_minutes_raw = 0
            if date_dt.weekday() != 6: # Não é Domingo
                is_holiday_today = self.is_holiday(date_str)
                if not (is_holiday_today and is_fichado): # Não é feriado para fichado
                    if date_dt.weekday() < 5: expected_minutes_raw = MINUTOS_JORNADA_SEG_SEX
                    elif date_dt.weekday() == 5: expected_minutes_raw = MINUTOS_JORNADA_SABADO
            
            dados_dia = work_map.get(date_str)
            minutos_trabalhados_dia = dados_dia.get('minutos', 0) if dados_dia else 0
            
            # Pega minutos abonados para estatística
            abono_min_dia = abonos_map.get(date_str, 0)
            stats['minutos_abonados_total'] += abono_min_dia

            # Contabiliza Faltas
            if expected_minutes_raw > 0 and minutos_trabalhados_dia == 0:
                if abono_min_dia > 0:
                    stats['faltas_abonadas'] += 1 # Se teve qualquer abono e não veio, é falta abonada
                else:
                    stats['faltas_nao_abonadas'] += 1
            elif minutos_trabalhados_dia > 0:
                stats['dias_trabalhados'] += 1

            # Contabiliza Atrasos
            if dados_dia and dados_dia['periodos']:
                try:
                    periods_json = json.loads(dados_dia['periodos'])
                    deducao_dia = 0
                    for p in periods_json:
                        deducao_dia += parse_hhmm_to_minutes(p.get('deducao_minutos', '00:00:00'))
                    if deducao_dia > 0:
                        stats['dias_com_atraso'] += 1
                        stats['atrasos_deduzidos_min'] += deducao_dia
                except:
                    pass

            # Simula Saldo
            excedente_dia = minutos_trabalhados_dia - expected_minutes # 'expected_minutes' já tem o abono
            saldo_bh_simulado += excedente_dia

            while saldo_bh_simulado >= MINUTOS_UNIDADE_EXTRA:
                saldo_bh_simulado -= MINUTOS_UNIDADE_EXTRA
                saldo_extras_simulado += 1
                stats['extras_geradas_periodo'] += 1
            while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                saldo_extras_simulado -= 1
                stats['extras_geradas_periodo'] -= 1

            punicao_do_dia = punicoes_map.get(date_str, 0)
            if punicao_do_dia > 0:
                stats['punicoes_count'] += 1
                stats['punicoes_min'] += punicao_do_dia
                
                saldo_bh_simulado -= punicao_do_dia
                while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                    saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                    saldo_extras_simulado -= 1
                    stats['extras_geradas_periodo'] -= 1

            current_date_iter += timedelta(days=1)

        stats['bh_end'] = saldo_bh_simulado
        stats['extras_end'] = saldo_extras_simulado
        stats['extras_geradas_periodo'] = stats['extras_end'] - stats['extras_start']

        return stats

# --- Função import_glog_txt ---
def import_glog_txt(filepath, db_manager, logger=print):
    employees_points_raw = defaultdict(lambda: defaultdict(list))
    unique_employees = set()
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f.readlines()[1:]: # Pula cabeçalho
                parts = re.split(r'\s+', line.strip())
                if len(parts) < 8: continue
                try:
                    matricula = str(parts[2]).zfill(8)
                    nome = str(parts[3]).strip()
                    if len(parts) >= 8 and parts[6] and parts[7]:
                        dt_str = f"{parts[6]} {parts[7]}"
                        dt = try_parse_datetime(dt_str)
                        if dt:
                            # Filtra pela constante global
                            if dt.date() < datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                                 continue # Ignora datas anteriores ao início
                            unique_employees.add((matricula, nome))
                            employees_points_raw[matricula][dt.date().isoformat()].append({"datetime": dt})
                        else:
                            logger(f"AVISO: Formato de data/hora inválido na linha: {line.strip()}")
                    else:
                        logger(f"AVISO: Dados de data/hora ausentes na linha: {line.strip()}")
                except IndexError:
                     logger(f"AVISO: Linha com formato inesperado (IndexError): {line.strip()}")
                except Exception as e:
                     logger(f"AVISO: Erro ao processar linha: {line.strip()} - Erro: {e}")
                     continue
    except Exception as e:
        logger(f"ERRO LEITURA ARQUIVO: {e}")
        return [], set()

    logger(f"Funcionários detectados no arquivo: {len(unique_employees)}")
    existing_matriculas = db_manager.get_all_funcionarios_matriculas()
    new_employees_list = []
    processed_matriculas_in_file = set()
    for matricula, nome in unique_employees:
        processed_matriculas_in_file.add(matricula)
        if matricula not in existing_matriculas:
            new_employees_list.append((matricula, nome))

    for matricula, dias in sorted(employees_points_raw.items()):
        func_info = db_manager.get_funcionario_info(matricula)
        sector = func_info.get('setor', 'N/D') if func_info else 'N/D'

        for data, pontos_brutos in sorted(dias.items()):
            # Checagem extra por segurança
            if data < SYSTEM_START_DATE:
                continue

            pontos_brutos.sort(key=lambda x: x["datetime"])
            periodos_trabalhados, minutos_trabalhados_decimal_total = [], 0
            horarios_sequenciais = [p["datetime"] for p in pontos_brutos]

            i = 0
            while i < len(horarios_sequenciais):
                entrada = horarios_sequenciais[i]
                saida = None
                
                if i + 1 < len(horarios_sequenciais):
                    saida = horarios_sequenciais[i+1]
                else:
                    pass # Última batida ímpar
                
                turno = "Manhã" if i < 2 else "Tarde"
                jornada_inicio = datetime.strptime(f"{data} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                minutes_late = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                delay_deduction_minutes = calculate_deduction(minutes_late, sector)
                
                if saida: # Par completo
                    if saida < entrada:
                       logger(f"AVISO: {matricula} {data}: Saída ({saida}) anterior à entrada ({entrada}). Ignorando período.")
                       i += 2
                       continue
                    inicio_efetivo = jornada_inicio + timedelta(minutes=delay_deduction_minutes)
                    inicio_real_contagem = max(entrada, inicio_efetivo)
                    duration_minutes_liquido = 0
                    if saida > inicio_real_contagem:
                        duration_minutes_liquido = (saida - inicio_real_contagem).total_seconds() / 60
                    duration_minutes_bruto = (saida - entrada).total_seconds() / 60
                    minutos_trabalhados_decimal_total += duration_minutes_liquido
                    periodos_trabalhados.append({
                        "entrada": str(entrada), "saida": str(saida),
                        "minutos_brutos": format_minutes_to_hms(duration_minutes_bruto),
                        "deducao_minutos": format_minutes_to_hms(delay_deduction_minutes),
                        "minutos_liquidos": format_minutes_to_hms(duration_minutes_liquido)
                    })
                    i += 2
                else: # Batida ímpar
                    logger(f"AVISO: {matricula} {data}: Batida ímpar detectada ({entrada}). Salva como incompleta.")
                    periodos_trabalhados.append({
                        "entrada": str(entrada), "saida": None,
                        "minutos_brutos": "00:00:00",
                        "deducao_minutos": format_minutes_to_hms(delay_deduction_minutes),
                        "minutos_liquidos": "00:00:00"
                    })
                    i += 1

            if periodos_trabalhados:
                db_manager.insert_horas_trabalhadas({
                    "matricula": matricula,
                    "data": data,
                    "minutos_totais": format_minutes_to_hms(minutos_trabalhados_decimal_total),
                    "periodos": periodos_trabalhados
                })
            elif len(horarios_sequenciais) > 0:
                logger(f"AVISO: {matricula} {data}: Nenhuns períodos de trabalho válidos formados a partir das batidas.")

    return new_employees_list, processed_matriculas_in_file


# --- Classe DateRangePicker ---
class DateRangePicker:
    """Um widget de calendário reutilizável que seleciona um intervalo de datas."""
    def __init__(self, parent, bg_color, style_colors): # Removido system_start_date_str
        self.frame = tk.Frame(parent, bg=bg_color)
        self.selected_start_date = None
        self.selected_end_date = None
        self.selecting_start = True

        self.style_colors = style_colors

        try:
            # Usa constante global
            min_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        except:
            min_date = None

        self.cal = Calendar(self.frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR',
                            background=style_colors['ACCENT_COLOR'], foreground="white", headersbackground=style_colors['ACCENT_COLOR'],
                            normalbackground=style_colors['LIGHT_BG'], weekendbackground="#172a45",
                            othermonthbackground=style_colors['BG_COLOR'], othermonthforeground="#6a7b9d",
                            selectbackground=style_colors['ACCENT_COLOR'],
                            mindate=min_date) # mindate definido aqui

        self.cal.pack(side=tk.LEFT, padx=(0, 20))
        self.cal.bind("<<CalendarSelected>>", self._on_calendar_click)

        self.cal.tag_config('start_date', background=style_colors['START_DATE_COLOR'], foreground='white')
        self.cal.tag_config('end_date', background=style_colors['END_DATE_COLOR'], foreground='white')
        self.cal.tag_config('range_date', background=style_colors['RANGE_BG_COLOR'], foreground=style_colors['FG_COLOR'])

        self.labels_frame = tk.Frame(self.frame, bg=bg_color)
        self.labels_frame.pack(side=tk.LEFT, anchor='n')

        tk.Label(self.labels_frame, text="Início:", bg=bg_color, fg=style_colors['FG_COLOR'], width=5, anchor='w').pack(pady=2)
        self.lbl_start = tk.Label(self.labels_frame, text="--/--/----", bg=bg_color, fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_start.pack()

        tk.Label(self.labels_frame, text="Fim:", bg=bg_color, fg=style_colors['FG_COLOR'], width=5, anchor='w').pack(pady=2)
        self.lbl_end = tk.Label(self.labels_frame, text="--/--/----", bg=bg_color, fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_end.pack()

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    # Removida a função update_mindate

    def _update_calendar_tags(self):
        self.cal.calevent_remove('all')
        if self.selected_start_date:
            self.cal.calevent_create(self.selected_start_date, 'Início', tags='start_date')
            self.lbl_start.config(text=self.selected_start_date.strftime("%d/%m/%Y"))
        else:
            self.lbl_start.config(text="--/--/----")

        if self.selected_end_date:
            self.cal.calevent_create(self.selected_end_date, 'Fim', tags='end_date')
            self.lbl_end.config(text=self.selected_end_date.strftime("%d/%m/%Y"))

            if self.selected_start_date and self.selected_start_date < self.selected_end_date:
                current_date = self.selected_start_date + timedelta(days=1)
                while current_date < self.selected_end_date:
                    self.cal.calevent_create(current_date, '', tags='range_date')
                    current_date += timedelta(days=1)
        else:
            self.lbl_end.config(text="--/--/----")

    def _on_calendar_click(self, event=None):
        try:
            clicked_date = self.cal.selection_get()
        except tk.TclError:
            return

        if not clicked_date: return

        try:
            # Re-lê a data mínima do próprio widget
            min_date = self.cal.cget('mindate')
            if clicked_date < min_date:
                clicked_date = min_date
                self.cal.selection_set(clicked_date)
        except:
            pass

        if self.selecting_start:
            self.selected_start_date = clicked_date
            self.selected_end_date = None
            self.selecting_start = False
            self.lbl_end.config(text="Selecione...")
        else:
            self.selected_end_date = clicked_date
            self.selecting_start = True
            if self.selected_start_date and self.selected_end_date and self.selected_end_date < self.selected_start_date:
                self.selected_start_date, self.selected_end_date = self.selected_end_date, self.selected_start_date

        self._update_calendar_tags()

    def get_dates(self):
        return self.selected_start_date, self.selected_end_date


# --- Classe App ---
class App:
    def __init__(self, root):
        self.db = DatabaseManager()
        # Removido self.SYSTEM_START_DATE
        self.root = root
        self.root.state('zoomed')
        self.root.title("WN Ponto Certo")
        try:
            self.root.iconbitmap(LOGO_ICON_PATH)
        except Exception as e:
            print(f"Aviso: Não foi possível carregar o ícone: {e}")
        self.root.configure(bg="#0a192f")
        self.root.minsize(1200, 700)

        try:
            # Usa constante global
            min_date_obj = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
            self.selected_start_date = max(date.today().replace(day=1), min_date_obj)
        except:
            self.selected_start_date = date.today().replace(day=1)

        self.selected_end_date = date.today()

        self.selecting_start = True
        self.unsaved_edits = {}
        self.editing_widgets = {}
        # Removido self.dynamic_calendar_widgets
        
        self.setup_styles()
        self.setup_ui()

        if hasattr(self, 'main_calendar'):
            self.main_calendar.selection_set(self.selected_start_date)
            self.on_calendar_click()
            self.main_calendar.selection_set(self.selected_end_date)
            self.on_calendar_click()

        self.root.protocol("WM_DELETE_WINDOW", self.on_app_close)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        self.BG_COLOR="#0a192f"; self.FG_COLOR="#ccd6f6"; self.LIGHT_BG="#112240"; self.ACCENT_COLOR="#008080"; self.HIGHLIGHT_COLOR="#40E0D0"; self.START_DATE_COLOR="#2ca3a3"; self.END_DATE_COLOR="#1f5f5f"; self.RANGE_BG_COLOR="#1a3b5c"; self.HOLIDAY_COLOR="#FF8C00"

        self.style_colors_dict = {
            'BG_COLOR': self.BG_COLOR, 'FG_COLOR': self.FG_COLOR, 'LIGHT_BG': self.LIGHT_BG,
            'ACCENT_COLOR': self.ACCENT_COLOR, 'HIGHLIGHT_COLOR': self.HIGHLIGHT_COLOR,
            'START_DATE_COLOR': self.START_DATE_COLOR, 'END_DATE_COLOR': self.END_DATE_COLOR,
            'RANGE_BG_COLOR': self.RANGE_BG_COLOR, 'HOLIDAY_COLOR': self.HOLIDAY_COLOR
        }

        style.configure('.', background=self.BG_COLOR, foreground=self.FG_COLOR, font=('Segoe UI', 10))
        style.configure('TButton', font=('Segoe UI', 10, 'bold'), background=self.ACCENT_COLOR, foreground='white', borderwidth=0, focusthickness=0, padding=8)
        style.map('TButton', background=[('active', '#006666')])
        style.configure('Delete.TButton', font=('Segoe UI', 10, 'bold'), background='#b30000', foreground='white', borderwidth=0, focusthickness=0, padding=8)
        style.map('Delete.TButton', background=[('active', '#800000')])
        style.configure("Treeview", rowheight=25, fieldbackground=self.LIGHT_BG, background=self.LIGHT_BG, foreground=self.FG_COLOR)
        style.configure("Treeview.Heading", font=('Segoe UI', 10, 'bold'), background=self.ACCENT_COLOR, foreground='white')
        style.map("Treeview.Heading", background=[('active', self.ACCENT_COLOR)])
        style.map('Treeview', background=[('selected', self.ACCENT_COLOR)])
        style.configure('TEntry', fieldbackground=self.LIGHT_BG, foreground=self.FG_COLOR, insertcolor=self.FG_COLOR)
        style.map('TEntry', fieldbackground=[('disabled', '#0a192f')], foreground=[('disabled', '#6a7b9d')])
        style.configure('TCombobox', fieldbackground=self.LIGHT_BG, background=self.LIGHT_BG, arrowcolor=self.FG_COLOR, foreground=self.FG_COLOR, selectbackground=self.LIGHT_BG, selectforeground=self.FG_COLOR)
        # --- FIX VISUALIZAÇÃO COMBOBOX ---
        style.map('TCombobox', foreground=[('readonly', 'Black')]) # Força texto branco para readonly
        # --- FIM FIX ---
        self.root.option_add('*TCombobox*Listbox.background', self.LIGHT_BG)
        self.root.option_add('*TCombobox*Listbox.foreground', self.FG_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', self.ACCENT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectForeground', self.FG_COLOR)
        style.configure('TLabelframe', background=self.BG_COLOR, bordercolor=self.ACCENT_COLOR)
        style.configure('TLabelframe.Label', foreground=self.HIGHLIGHT_COLOR, background=self.BG_COLOR, font=('Segoe UI', 9, 'bold'))
        style.configure('DateRange.TLabel', background=self.RANGE_BG_COLOR, foreground=self.FG_COLOR)
        style.configure('StartDate.TLabel', background=self.START_DATE_COLOR, foreground='white', font=('Segoe UI', 10, 'bold'))
        style.configure('EndDate.TLabel', background=self.END_DATE_COLOR, foreground='white', font=('Segoe UI', 10, 'bold'))
        style.configure('TCheckbutton', background=self.BG_COLOR, foreground=self.FG_COLOR, indicatorcolor=self.ACCENT_COLOR, font=('Segoe UI', 10))
        style.map('TCheckbutton',
                  indicatorcolor=[('selected', self.HIGHLIGHT_COLOR), ('active', self.ACCENT_COLOR)],
                  background=[('active', self.BG_COLOR)])


    def setup_ui(self):
        main_frame = tk.Frame(self.root, bg="#0a192f")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        main_frame.grid_rowconfigure(1, weight=1)
        main_frame.grid_columnconfigure(0, weight=3)
        main_frame.grid_columnconfigure(1, weight=1)

        top_frame = tk.Frame(main_frame, bg="#0a192f")
        top_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        header_frame = tk.Frame(top_frame, bg="#0a192f")
        header_frame.pack(fill=tk.X)
        try:
            logo_img = PILImage.open(LOGO_PATH)
            logo_img = logo_img.resize((45, 45), Image.Resampling.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(logo_img)
            logo_label = tk.Label(header_frame, image=self.logo_photo, bg="#0a192f")
            logo_label.pack(side=tk.LEFT, padx=(0, 10))
        except Exception as e:
            print(f"ERRO logo: {e}")
        app_title = tk.Label(header_frame, text="WN Ponto Certo", font=("Segoe UI", 20, "bold"), fg="white", bg="#0a192f")
        app_title.pack(side=tk.LEFT)

        actions_frame = tk.Frame(top_frame, bg="#0a192f")
        actions_frame.pack(fill=tk.X, pady=(10,0))
        ttk.Button(actions_frame, text="📂 Importar", command=self.on_import, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="✏️ Editar Func", command=self.on_edit_employee, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="📅 Feriados", command=self.on_manage_holidays, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="💰 Pagar Saldo", command=self.on_extra_payment, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text=" Punição", command=self.on_add_punishment, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        # --- ADICIONE ESTAS 3 LINHAS ---
        ttk.Button(actions_frame, text="Saldos Iniciais", command=self.on_edit_initial_balance, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="Abonar Falta", command=self.on_abone_falta, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="Relatório Detalhado", command=self.on_detailed_report, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        # --- FIM DA ADIÇÃO ---
        ttk.Button(actions_frame, text="📄 Exportar Log", command=self.on_export_log, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="🚪 Sair", command=self.on_app_close, style='TButton').pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(main_frame, text=" Log ", style='TLabelframe')
        log_frame.grid(row=1, column=1, sticky="nsew", pady=5, padx=(5, 0))
        self.log_area = scrolledtext.ScrolledText(log_frame, bg="#112240", fg="#a8b2d1", insertbackground="white", font=("Consolas", 9), relief=tk.FLAT, borderwidth=5)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.setup_point_viewer(main_frame)

    def on_app_close(self):
        if self.unsaved_edits:
            answer = messagebox.askyesnocancel("Alterações Não Salvas",
                                             "Você possui alterações não salvas.\nDeseja salvar antes de sair?",
                                             icon='warning')
            if answer is None: # Cancel
                return
            elif answer is True: # Yes
                self.append_log("Salvando alterações antes de sair...")
                self.commit_all_changes(from_exit=True)
                self.root.destroy()
            else: # No
                self.root.destroy()
        else:
            self.root.destroy()

    def on_import(self):
        filepath = filedialog.askopenfilename(title="Selecione o arquivo TXT", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not filepath: return
        try:
            self.append_log(f"Arquivo selecionado: {filepath}")
            self.append_log("Iniciando importação...")
            new_employees, processed_matriculas = import_glog_txt(filepath, self.db, logger=self.append_log)
            
            # Removido bloco de atualização dinâmica de mindate

            if new_employees:
                self.append_log(f"{len(new_employees)} novos funcionários. Complete o cadastro.")
                for matricula, nome in new_employees:
                    self.prompt_for_new_employee_details(matricula, nome)
                self.append_log("Cadastro concluído.")
            if processed_matriculas:
                self.append_log(f"Recalculando saldos para {len(processed_matriculas)} funcionários...")
                recalc_errors = 0
                for matricula in processed_matriculas:
                    try:
                        self.db.recalculate_full_balance_for_employee(matricula)
                    except Exception as e:
                        self.append_log(f"ERRO ao recalcular saldo para {matricula}: {e}")
                        recalc_errors += 1
                if recalc_errors == 0:
                    self.append_log("Saldos recalculados.")
                else:
                    self.append_log(f"Recálculo concluído com {recalc_errors} erro(s). Verifique o log.")

            self.append_log("Importação concluída ✅")
            self.update_employee_filter()
            self.load_point_viewer(force_reload=True)
            self._update_calendar_tags()
        except NameError as ne:
             self.append_log(f"Erro importação: {ne}. A função 'import_glog_txt' não foi encontrada.")
             messagebox.showerror("Erro de Código", f"Erro interno: {ne}\nA função 'import_glog_txt' pode estar faltando no código.")
        except Exception as e:
            self.append_log(f"Erro importação: {e}")
            messagebox.showerror("Erro", str(e))


    def prompt_for_new_employee_details(self, matricula, nome):
        win = tk.Toplevel(self.root); win.title("Novo Funcionário")
        win.configure(bg=self.BG_COLOR); win.state('zoomed'); win.minsize(600, 500)
        win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR)
        main_frame.pack(expand=True)

        frame_form = tk.Frame(main_frame, bg=self.BG_COLOR); frame_form.pack(padx=20, pady=20, fill="both", expand=True)
        tk.Label(frame_form, text="Complete o cadastro:", bg=self.BG_COLOR, fg=self.HIGHLIGHT_COLOR, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10)); tk.Label(frame_form, text=f"Matrícula: {matricula}", bg=self.BG_COLOR, fg=self.FG_COLOR).pack(anchor="w"); tk.Label(frame_form, text=f"Nome: {nome}", bg=self.BG_COLOR, fg=self.FG_COLOR).pack(anchor="w", pady=(0, 20))

        frame_fichado = tk.Frame(frame_form, bg=self.BG_COLOR); frame_fichado.pack(fill='x', pady=5); tk.Label(frame_fichado, text="É Fichado?", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); cmb_fichado = ttk.Combobox(frame_fichado, values=LISTA_FICHADO, state="readonly", width=20); cmb_fichado.pack(side=tk.LEFT); cmb_fichado.set("Sim")

        frame_setor = tk.Frame(frame_form, bg=self.BG_COLOR); frame_setor.pack(fill='x', pady=5); tk.Label(frame_setor, text="Setor:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); cmb_setor = ttk.Combobox(frame_setor, values=LISTA_SETORES, state="readonly", width=20); cmb_setor.pack(side=tk.LEFT); cmb_setor.set("Operacional")

        frame_bh = tk.Frame(frame_form, bg=self.BG_COLOR); frame_bh.pack(fill='x', pady=5); tk.Label(frame_bh, text="BH Inicial (HH:MM):", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); entry_bh_inicial = ttk.Entry(frame_bh, width=22); entry_bh_inicial.pack(side=tk.LEFT); entry_bh_inicial.insert(0, "00:00")

        frame_extras = tk.Frame(frame_form, bg=self.BG_COLOR); frame_extras.pack(fill='x', pady=5); tk.Label(frame_extras, text="Extras Iniciais (Un):", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); entry_extras_inicial = ttk.Entry(frame_extras, width=22); entry_extras_inicial.pack(side=tk.LEFT); entry_extras_inicial.insert(0, "0")

        def save_new_employee():
            fichado_str = cmb_fichado.get(); setor = cmb_setor.get();
            if not fichado_str or not setor: messagebox.showerror("Erro", "Campos obrigatórios.", parent=win); return

            bh_inicial_str = entry_bh_inicial.get()
            extras_inicial_str = entry_extras_inicial.get()

            bh_minutos = parse_hhmm_to_minutes(bh_inicial_str)
            try:
                extras_int = int(extras_inicial_str)
            except ValueError:
                messagebox.showerror("Erro", "Valor de Extras Iniciais inválido. Use apenas números.", parent=win)
                return

            fichado_val = 1 if fichado_str == "Sim" else 0
            dados = {
                "matricula": matricula,
                "nome": nome,
                "fichado": fichado_val,
                "setor": setor,
                "banco_horas_inicial": bh_minutos,
                "extras_disponiveis_inicial": extras_int,
                "banco_horas": bh_minutos,
                "extras_disponiveis": extras_int
            }

            try:
                self.db.insert_funcionario(dados);
                self.append_log(f"Funcionário {nome} ({matricula}) cadastrado com BH: {format_minutes_to_hms(bh_minutos)} e Extras: {extras_int}.");
                win.destroy()
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível salvar: {e}", parent=win)

        btn_salvar = ttk.Button(frame_form, text="✅ Salvar", style='TButton', command=save_new_employee); btn_salvar.pack(pady=20)
        ttk.Button(frame_form, text="Sair", style='Delete.TButton', command=win.destroy).pack(pady=5)

        self.root.wait_window(win)

    def on_edit_employee(self):
        win = tk.Toplevel(self.root); win.title("Editar Dados Cadastrais")
        win.configure(bg=self.BG_COLOR); win.state('zoomed'); win.minsize(800, 600)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        selected_matricula = tk.StringVar(); main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20); main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Button(main_frame, text="Sair", style='Delete.TButton', command=win.destroy, width=10).pack(anchor='e', pady=(0,10))

        tree_frame = ttk.LabelFrame(main_frame, text=" Selecione um funcionário", style='TLabelframe'); tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15)); tree_frame.grid_rowconfigure(0, weight=1); tree_frame.grid_columnconfigure(0, weight=1)
        columns = ("Matrícula", "Nome", "Fichado", "Setor"); employee_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=employee_tree.yview); h_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=employee_tree.xview)
        employee_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set); employee_tree.grid(row=0, column=0, sticky='nsew'); v_scroll.grid(row=0, column=1, sticky='ns'); h_scroll.grid(row=1, column=0, sticky='ew')
        col_widths = {"Matrícula": 100, "Nome": 250, "Fichado": 80, "Setor": 120}; [employee_tree.heading(col, text=col) or employee_tree.column(col, width=col_widths.get(col, 100), anchor=tk.W, stretch=tk.YES if col=="Nome" else tk.NO) for col in columns]
        edit_frame = ttk.LabelFrame(main_frame, text=" Editar Informações", style='TLabelframe'); edit_frame.pack(fill=tk.X, pady=10)
        frame_fichado = tk.Frame(edit_frame, bg=self.BG_COLOR); frame_fichado.pack(fill='x', pady=5, anchor='w', padx=10); tk.Label(frame_fichado, text="É Fichado?", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); cmb_fichado = ttk.Combobox(frame_fichado, values=LISTA_FICHADO, state="readonly", width=20); cmb_fichado.pack(side=tk.LEFT, padx=5)
        frame_setor = tk.Frame(edit_frame, bg=self.BG_COLOR); frame_setor.pack(fill='x', pady=5, anchor='w', padx=10); tk.Label(frame_setor, text="Setor:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); cmb_setor = ttk.Combobox(frame_setor, values=LISTA_SETORES, state="readonly", width=20); cmb_setor.pack(side=tk.LEFT, padx=5)
        btn_salvar = ttk.Button(edit_frame, text="✅ Salvar Alterações", width=30, style='TButton', state="disabled"); btn_salvar.pack(pady=15)
        def refresh_employee_list():
            [employee_tree.delete(i) for i in employee_tree.get_children()]; funcionarios = self.db.get_all_employees_with_details()
            for i, func in enumerate(funcionarios): fichado_str = "Sim" if func.get('fichado', 0) == 1 else "Não"; setor_str = func.get('setor', 'N/D'); values = (func['matricula'], func['nome'], fichado_str, setor_str); tag = 'evenrow' if i % 2 == 0 else 'oddrow'; employee_tree.insert("", "end", values=values, iid=func['matricula'], tags=(tag,))
        def on_employee_select(event=None):
            selected_items = employee_tree.selection()
            if not selected_items: selected_matricula.set(""); cmb_fichado.set(""); cmb_setor.set(""); btn_salvar.config(state="disabled"); return
            selected_iid = selected_items[0]; item_values = employee_tree.item(selected_iid, 'values');
            if not item_values: return
            selected_matricula.set(item_values[0]); fichado_str = item_values[2]; setor_str = item_values[3]; cmb_fichado.set(fichado_str); cmb_setor.set(setor_str if setor_str in LISTA_SETORES else 'N/D'); btn_salvar.config(state="normal")
        employee_tree.bind("<<TreeviewSelect>>", on_employee_select)
        def save_changes():
            matricula = selected_matricula.get();
            if not matricula: messagebox.showerror("Erro", "Funcionário não selecionado.", parent=win); return
            fichado_str = cmb_fichado.get(); setor = cmb_setor.get(); fichado_val = 1 if fichado_str == "Sim" else 0; selected_items = employee_tree.selection(); nome_func = employee_tree.item(selected_items[0], 'values')[1] if selected_items else ""
            if messagebox.askyesno("Confirmar", f"Atualizar {nome_func} ({matricula})?", parent=win):
                info_antes = self.db.get_funcionario_info(matricula)
                if self.db.update_employee_details(matricula, fichado_val, setor):
                    messagebox.showinfo("Sucesso", "Dados atualizados!", parent=win)
                    refresh_employee_list()
                    employee_tree.selection_remove(employee_tree.selection())
                    selected_matricula.set(""); cmb_fichado.set(""); cmb_setor.set(""); btn_salvar.config(state="disabled")
                    if info_antes.get('fichado') != fichado_val or info_antes.get('setor') != setor:
                        try:
                            self.db.recalculate_full_balance_for_employee(matricula)
                            self.append_log(f"Recalculando saldo para {matricula} devido à alteração cadastral.")
                        except Exception as e:
                            self.append_log(f"ERRO ao recalcular saldo para {matricula} após alteração: {e}")
                            messagebox.showerror("Erro Recálculo", f"Erro ao recalcular saldo para {matricula}:\n{e}", parent=win)
                    self.load_point_viewer(force_reload=True)
                else:
                    messagebox.showerror("Erro", "Não foi possível salvar.", parent=win)
        btn_salvar.config(command=save_changes); refresh_employee_list()

    def on_add_punishment(self):
        win = tk.Toplevel(self.root); win.title("Adicionar Punição")
        win.configure(bg=self.BG_COLOR);
        win.state('zoomed'); win.minsize(600, 700)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR)
        main_frame.pack(expand=True)

        form_frame = tk.Frame(main_frame, bg=self.BG_COLOR, padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy, width=10).pack(anchor='e', pady=(0,10))

        tk.Label(form_frame, text="1. Func:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]; cmb_func = ttk.Combobox(form_frame, values=nomes, state="readonly", width=50); cmb_func.pack(anchor="w", pady=(0, 15))

        try:
            min_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        except:
            min_date = None

        tk.Label(form_frame, text="2. Data:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); cal_punicao = Calendar(form_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080", mindate=min_date); cal_punicao.pack(anchor="w", pady=(0, 15))
        # Removida adição à lista dinâmica
        
        tk.Label(form_frame, text="3. Tempo (HH:MM):", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); entry_tempo = ttk.Entry(form_frame, width=15); entry_tempo.pack(anchor="w", pady=(0, 15))
        tk.Label(form_frame, text="4. Motivo:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); entry_motivo = ttk.Entry(form_frame, width=50); entry_motivo.pack(anchor="w", fill="x", pady=(0, 20))

        def save_punishment():
             selection = cmb_func.get();
             if not selection: messagebox.showerror("Erro", "Funcionário não selecionado.", parent=win); return
             matricula = selection.split(" - ")[0]; nome_func = " ".join(selection.split(" - ")[1:])
             date_str = cal_punicao.get_date(); tempo_str = entry_tempo.get().strip(); motivo = entry_motivo.get().strip()

             if date_str < SYSTEM_START_DATE:
                 messagebox.showerror("Erro", f"Não é possível registrar punições antes de {SYSTEM_START_DATE}.", parent=win)
                 return

             if not tempo_str: messagebox.showerror("Erro", "Tempo obrigatório.", parent=win); return
             if not motivo: messagebox.showerror("Erro", "Motivo obrigatório.", parent=win); return

             minutos_descontados = parse_hhmm_to_minutes(tempo_str)
             if minutos_descontados == 0:
                  messagebox.showerror("Erro", "Formato de tempo inválido (use HH:MM) ou tempo é zero.", parent=win); return
             if minutos_descontados < 0:
                 minutos_descontados = abs(minutos_descontados)

             confirm_msg = (f"Confirmar {format_minutes_to_hms(minutos_descontados)} para {nome_func}\nData: {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')}?\nMotivo: {motivo}\n\nATENÇÃO: A punição será registrada e o saldo recalculado.")
             if messagebox.askyesno("Confirmar Punição", confirm_msg, parent=win):
                 if self.db.add_punicao(matricula, date_str, minutos_descontados, motivo):
                     messagebox.showinfo("Sucesso", "Punição registrada! O saldo será recalculado.", parent=win)
                     self.append_log(f"PUNIÇÃO REGISTRADA: {matricula} - {date_str} - {format_minutes_to_hms(minutos_descontados)} - {motivo}")
                     cmb_func.set(''); entry_tempo.delete(0, 'end'); entry_motivo.delete(0, 'end')
                     try:
                         self.db.recalculate_full_balance_for_employee(matricula)
                         self.append_log(f"Recalculando saldo para {matricula} após registro de punição.")
                     except Exception as e:
                         self.append_log(f"ERRO ao recalcular saldo para {matricula} após punição: {e}")
                         messagebox.showerror("Erro Recálculo", f"Erro ao recalcular saldo para {matricula}:\n{e}", parent=win)
                     self.load_point_viewer(force_reload=True);
                     self._update_calendar_tags()
                 else: messagebox.showerror("Erro", "Não foi possível salvar a punição.", parent=win)

        btn_salvar_punicao = ttk.Button(form_frame, text="✅ Registrar Punição", style='TButton', command=save_punishment); btn_salvar_punicao.pack()

    def on_manage_holidays(self):
        win = tk.Toplevel(self.root)
        win.title("Gerenciar Feriados")
        win.configure(bg=self.BG_COLOR)
        win.state('zoomed'); win.minsize(1024, 768)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        form_frame = ttk.LabelFrame(main_frame, text=" Adicionar/Editar Feriado ", style='TLabelframe')
        form_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        try:
            min_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        except:
            min_date = None

        tk.Label(form_frame, text="1. Data:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 5), padx=10)
        cal_feriado = Calendar(form_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR',
                               background="#008080", foreground="white", headersbackground="#008080",
                               mindate=min_date)
        cal_feriado.pack(anchor="w", pady=(0, 15), padx=10)
        # Removida adição à lista dinâmica

        tk.Label(form_frame, text="2. Descrição:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        entry_descricao = ttk.Entry(form_frame, width=30)
        entry_descricao.pack(anchor="w", fill="x", pady=(0, 15), padx=10)

        tk.Label(form_frame, text="3. Tipo:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        cmb_tipo = ttk.Combobox(form_frame, values=LISTA_TIPO_FERIADO, state="readonly", width=28)
        cmb_tipo.pack(anchor="w", padx=10)
        cmb_tipo.set("Municipal")

        chk_recorrente_var = tk.IntVar()
        chk_recorrente = ttk.Checkbutton(form_frame, text="Recorrente (todo ano)", variable=chk_recorrente_var, style='TCheckbutton')
        chk_recorrente.pack(anchor='w', padx=10, pady=10)

        btn_save = ttk.Button(form_frame, text="✅ Salvar (Novo/Editar)", style='TButton')
        btn_save.pack(pady=10, padx=10, fill=tk.X)

        btn_clear = ttk.Button(form_frame, text="Limpar Formulário", style='TButton')
        btn_clear.pack(pady=5, padx=10, fill=tk.X)

        btn_delete = ttk.Button(form_frame, text="🗑️ Remover Selecionado", style='Delete.TButton')
        btn_delete.pack(pady=(15, 5), padx=10, fill=tk.X)

        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy).pack(side=tk.BOTTOM, pady=10, padx=10, fill=tk.X)

        list_frame = ttk.LabelFrame(main_frame, text=" Feriados Cadastrados ", style='TLabelframe')
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        tree_columns = ("Data", "Descrição", "Tipo", "Recorrente")
        tree_feriados = ttk.Treeview(list_frame, columns=tree_columns, show="headings", selectmode="browse")

        v_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree_feriados.yview)
        h_scroll = ttk.Scrollbar(list_frame, orient="horizontal", command=tree_feriados.xview)
        tree_feriados.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)

        tree_feriados.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        h_scroll.grid(row=1, column=0, sticky='ew')

        col_widths = {"Data": 100, "Descrição": 200, "Tipo": 100, "Recorrente": 80}
        for col in tree_columns:
            anchor = tk.W if col == "Descrição" else tk.CENTER
            tree_feriados.heading(col, text=col)
            tree_feriados.column(col, width=col_widths.get(col, 100), anchor=anchor, stretch=tk.YES if col == "Descrição" else tk.NO)

        def clear_form():
            cal_feriado.selection_set(date.today())
            entry_descricao.delete(0, tk.END)
            cmb_tipo.set("Municipal")
            chk_recorrente_var.set(0)
            if tree_feriados.selection():
                tree_feriados.selection_remove(tree_feriados.selection())

        def refresh_holiday_list():
            [tree_feriados.delete(i) for i in tree_feriados.get_children()]

            spec_list = self.db.get_all_specific_holidays()
            for i, h in enumerate(spec_list):
                try:
                    data_fmt = datetime.strptime(h['data'], '%Y-%m-%d').strftime('%d/%m/%Y')
                except:
                    data_fmt = h['data']
                values = (data_fmt, h['descricao'], h['tipo'], "Não")
                iid = f"spec_{h['id']}"
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree_feriados.insert("", "end", values=values, iid=iid, tags=(tag,))

            rec_list = self.db.get_all_recurring_holidays()
            for i, h in enumerate(rec_list):
                data_fmt = f"{h['dia']:02}/{h['mes']:02}"
                values = (data_fmt, h['descricao'], h['tipo'], "Sim")
                iid = f"rec_{h['id']}"
                tag = 'evenrow' if (i + len(spec_list)) % 2 == 0 else 'oddrow'
                tree_feriados.insert("", "end", values=values, iid=iid, tags=(tag,))

        def on_holiday_select(event=None):
            selected_items = tree_feriados.selection()
            if not selected_items:
                return

            iid = selected_items[0]
            item_data = tree_feriados.item(iid, 'values')

            descricao, tipo, is_rec_str = item_data[1], item_data[2], item_data[3]

            entry_descricao.delete(0, tk.END)
            entry_descricao.insert(0, descricao)
            cmb_tipo.set(tipo)

            if is_rec_str == "Sim":
                chk_recorrente_var.set(1)
                dia_str, mes_str = item_data[0].split('/')
                try:
                    current_year = cal_feriado.get_displayed_month()[1]
                    data_dt = date(current_year, int(mes_str), int(dia_str))
                    cal_feriado.selection_set(data_dt)
                except ValueError:
                    try:
                       data_dt = date(current_year + 1, int(mes_str), int(dia_str))
                       cal_feriado.selection_set(data_dt)
                    except:
                       pass
            else:
                chk_recorrente_var.set(0)
                try:
                    data_dt = datetime.strptime(item_data[0], '%d/%m/%Y').date()
                    cal_feriado.selection_set(data_dt)
                except:
                    pass

        def save_holiday():
            try:
                data_dt = cal_feriado.selection_get()
            except:
                messagebox.showerror("Erro", "Data inválida.", parent=win)
                return

            desc = entry_descricao.get().strip()
            tipo = cmb_tipo.get()
            is_rec = chk_recorrente_var.get() == 1

            if not desc or not tipo:
                messagebox.showerror("Erro", "Descrição e Tipo são obrigatórios.", parent=win)
                return

            if not is_rec and data_dt < datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                messagebox.showerror("Erro", f"Não é possível registrar feriados específicos antes de {SYSTEM_START_DATE}.", parent=win)
                return

            selected_iid = tree_feriados.selection()
            if selected_iid:
                iid = selected_iid[0]
                if iid.startswith('spec_'):
                    self.db.delete_specific_holiday(iid.split('_')[1])
                elif iid.startswith('rec_'):
                    self.db.delete_recurring_holiday(iid.split('_')[1])

            success = False
            if is_rec:
                if self.db.add_recurring_holiday(data_dt.day, data_dt.month, desc, tipo):
                    self.append_log(f"FERIADO RECORRENTE: {data_dt.day}/{data_dt.month} - {desc} salvo.")
                    success = True
                else:
                    messagebox.showerror("Erro", "Não foi possível salvar o feriado recorrente.", parent=win)
            else:
                if self.db.add_holiday(data_dt.isoformat(), desc, tipo):
                     self.append_log(f"FERIADO: {data_dt.isoformat()} - {desc} salvo.")
                     success = True
                else:
                    messagebox.showerror("Erro", "Não foi possível salvar o feriado específico.", parent=win)

            if success:
                refresh_holiday_list()
                clear_form()
                messagebox.showinfo("Recalculando", "Feriado salvo. Os saldos de todos os funcionários serão recalculados. Isso pode demorar.", parent=win)
                self.append_log("Recalculando saldos devido a alteração de feriado...");
                recalc_errors = 0
                all_employees = self.db.get_all_funcionarios()
                for emp in all_employees:
                    try:
                        self.db.recalculate_full_balance_for_employee(emp['matricula'])
                    except Exception as e:
                        self.append_log(f"ERRO ao recalcular saldo para {emp['matricula']} após salvar feriado: {e}")
                        recalc_errors += 1
                if recalc_errors == 0:
                    self.append_log("Recálculo completo.")
                    messagebox.showinfo("Concluído", "Saldos recalculados.", parent=win)
                else:
                    self.append_log(f"Recálculo concluído com {recalc_errors} erro(s). Verifique o log.")
                    messagebox.showwarning("Atenção", f"Recálculo concluído com {recalc_errors} erro(s).\nVerifique o log para mais detalhes.", parent=win)

                self._update_calendar_tags()
                self.load_point_viewer(force_reload=True)

        def delete_holiday():
            selected_iid = tree_feriados.selection()
            if not selected_iid:
                messagebox.showerror("Erro", "Nenhum feriado selecionado.", parent=win)
                return

            iid = selected_iid[0]
            item_data = tree_feriados.item(iid, 'values')
            desc = item_data[1]

            if not messagebox.askyesno("Confirmar Remoção", f"Tem certeza que deseja remover o feriado '{desc}'?", parent=win):
                return

            success = False
            if iid.startswith('spec_'):
                success = self.db.delete_specific_holiday(iid.split('_')[1])
            elif iid.startswith('rec_'):
                success = self.db.delete_recurring_holiday(iid.split('_')[1])

            if success:
                self.append_log(f"FERIADO REMOVIDO: {desc}")
                refresh_holiday_list()
                clear_form()
                messagebox.showinfo("Recalculando", "Feriado removido. Os saldos de todos os funcionários serão recalculados. Isso pode demorar.", parent=win)
                self.append_log("Recalculando saldos...");
                recalc_errors = 0
                all_employees = self.db.get_all_funcionarios()
                for emp in all_employees:
                    try:
                        self.db.recalculate_full_balance_for_employee(emp['matricula'])
                    except Exception as e:
                       self.append_log(f"ERRO ao recalcular saldo para {emp['matricula']} após remover feriado: {e}")
                       recalc_errors += 1
                if recalc_errors == 0:
                    self.append_log("Recálculo completo.")
                    messagebox.showinfo("Concluído", "Saldos recalculados.", parent=win)
                else:
                    self.append_log(f"Recálculo concluído com {recalc_errors} erro(s). Verifique o log.")
                    messagebox.showwarning("Atenção", f"Recálculo concluído com {recalc_errors} erro(s).\nVerifique o log para mais detalhes.", parent=win)

                self._update_calendar_tags()
                self.load_point_viewer(force_reload=True)
            else:
                messagebox.showerror("Erro", "Não foi possível remover o feriado.", parent=win)

        btn_save.config(command=save_holiday)
        btn_clear.config(command=clear_form)
        btn_delete.config(command=delete_holiday)
        tree_feriados.bind("<<TreeviewSelect>>", on_holiday_select)

        refresh_holiday_list()


    def on_extra_payment(self, *args):
        win = tk.Toplevel(self.root)
        win.title("Pagamento e Saldos")
        win.configure(bg=self.BG_COLOR)
        win.state('zoomed'); win.minsize(800, 800)
        win.resizable(False, True)
        win.transient(self.root)
        win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Button(main_frame, text="Sair", style='Delete.TButton', command=win.destroy, width=10).pack(anchor='e', pady=(0,10))

        tk.Label(main_frame, text="1. Selecione o Funcionário:", bg=self.BG_COLOR, fg=self.HIGHLIGHT_COLOR, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 5))
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]
        cmb_func = ttk.Combobox(main_frame, values=nomes, state="readonly", width=60)
        cmb_func.pack(anchor="w", pady=(0, 15))

        details_frame = tk.Frame(main_frame, bg=self.BG_COLOR)
        details_frame.pack(fill=tk.BOTH, expand=True)

        widgets = {}
        data_vars = {
            "partial_salary_var": tk.StringVar(value="Não"),
            "fichado_info": {},
            "nao_fichado_info": {}
        }
        
        # Removida lista dynamic_drp_widgets

        def clear_details_frame():
            for widget in details_frame.winfo_children():
                widget.destroy()
            widgets.clear()
            data_vars["fichado_info"].clear()
            data_vars["nao_fichado_info"].clear()
            # Removida limpeza da lista dinâmica


        def is_sunday_or_holiday(date_obj):
            if date_obj.weekday() == 6:
                return True
            if self.db.is_holiday(date_obj.isoformat()):
                return True
            return False

        def generate_pdf_fichado(matricula, nome, func_info, payment_details):
            filepath = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], title="Salvar Relatório de Pagamento", initialfile=f"Pagamento_{nome.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf")
            if not filepath:
                return

            try:
                doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
                styles = getSampleStyleSheet()
                story = []

                style_title = styles['h1']
                style_title.alignment = 1
                style_title.textColor = colors.teal

                if LOGO_PATH.exists():
                    try:
                        story.append(Image(LOGO_PATH, width=4.5*cm, height=4.5*cm, hAlign='CENTER'))
                        story.append(Spacer(1, 0.5*cm))
                    except Exception as e:
                        print(f"Erro ao adicionar logo ao PDF: {e}")

                story.append(Paragraph("Recibo de Pagamento", style_title))
                story.append(Spacer(1, 1*cm))

                story.append(Paragraph(f"<b>Funcionário:</b> {nome}", styles['Normal']))
                story.append(Paragraph(f"<b>Matrícula:</b> {matricula}", styles['Normal']))
                story.append(Paragraph(f"<b>Status:</b> Fichado", styles['Normal']))
                story.append(Spacer(1, 1*cm))

                table_data = [['Item', 'Quantidade', 'Valor Unitário (R$)', 'Total (R$)']]
                total_pago = 0

                if payment_details['extras_qty'] > 0:
                    total_extras = payment_details['extras_qty'] * payment_details['extras_valor']
                    total_pago += total_extras
                    table_data.append([
                        'Pagamento de Extras',
                        f"{payment_details['extras_qty']} un.",
                        f"{payment_details['extras_valor']:.2f}",
                        f"{total_extras:.2f}"
                    ])

                if payment_details['pay_partial_salary']:
                    dias_periodo = (payment_details['end_date'] - payment_details['start_date']).days + 1
                    valor_diaria = payment_details['salario_mensal'] / 30
                    total_parcial = valor_diaria * dias_periodo
                    total_pago += total_parcial
                    table_data.append([
                        f"Salário Parcial ({payment_details['start_date'].strftime('%d/%m')} a {payment_details['end_date'].strftime('%d/%m')})",
                        f"{dias_periodo} dias",
                        f"{valor_diaria:.2f}",
                        f"{total_parcial:.2f}"
                    ])

                table_data.append(['TOTAL PAGO', '', '', f"R$ {total_pago:.2f}"])

                t = Table(table_data, colWidths=[6*cm, 3*cm, 4*cm, 4*cm])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.teal),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0,0), (-1,0), 12),
                    ('BACKGROUND', (0,1), (-1,-2), colors.beige),
                    ('GRID', (0,0), (-1,-1), 1, colors.black),
                    ('BACKGROUND', (0,-1), (-1,-1), colors.darkgrey),
                    ('TEXTCOLOR', (0,-1), (-1,-1), colors.whitesmoke),
                    ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
                ]))
                story.append(t)
                story.append(Spacer(1, 1*cm))

                # --- INÍCIO DA MODIFICAÇÃO (Adicionar Estatísticas) ---
                report_stats = payment_details.get('report_stats')
                if report_stats:
                    story.append(Paragraph(f"<b>Estatísticas do Período ({payment_details['start_date'].strftime('%d/%m')} a {payment_details['end_date'].strftime('%d/%m')})</b>", styles['h2']))
                    
                    stats_data = [
                        ['Faltas Totais (dias com 0h):', f"{report_stats['total_absences']} dia(s)"],
                        ['Faltas Parciais (dias < jornada):', f"{report_stats['partial_absences']} dia(s)"],
                        ['Dias com Atraso (desconto):', f"{report_stats['days_with_delay']} dia(s)"],
                        ['Total Descontado (Atrasos):', f"{format_minutes_to_hms(report_stats['total_delay_discount'])}"],
                        ['Punições no Período:', f"{report_stats['punishment_count']}"],
                        ['Total Descontado (Punições):', f"{format_minutes_to_hms(report_stats['total_punishment_discount'])}"]
                    ]
                    
                    stats_table = Table(stats_data, colWidths=[8*cm, 4*cm])
                    stats_table.setStyle(TableStyle([
                        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
                        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
                        ('FONTSIZE', (0,0), (-1,-1), 9),
                        ('TOPPADDING', (0,0), (-1,-1), 4),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                    ]))
                    story.append(stats_table)
                    story.append(Spacer(1, 1*cm))
                # --- FIM DA MODIFICAÇÃO ---


                story.append(Paragraph("<b>Saldos Remanescentes (Após Pagamento)</b>", styles['h2']))
                story.append(Paragraph(f"<b>Extras:</b> {int(func_info.get('extras_disponiveis', 0))}", styles['Normal']))
                story.append(Paragraph(f"<b>Banco de Horas:</b> {format_minutes_to_hms(func_info.get('banco_horas', 0))}", styles['Normal']))

                # --- INÍCIO DA MODIFICAÇÃO (FICHADO) ---
                try:
                    remaining_bh = func_info.get('banco_horas', 0)
                    
                    # --- AJUSTE SOLICITADO ---
                    # Determina a data base para encontrar o próximo dia útil
                    start_search_date = date.today() # Padrão
                    if payment_details.get('pay_partial_salary') and payment_details.get('end_date'):
                        start_search_date = payment_details['end_date']
                    # --- FIM AJUSTE SOLICITADO ---

                    # Esta função é para 'fichado', então is_fichado=True
                    next_business_day = self.find_next_business_day(start_search_date, is_fichado=True)
                    target_exit_time = self.calculate_bh_zero_exit(remaining_bh, next_business_day)
                    
                    story.append(Spacer(1, 0.5*cm))
                    story.append(Paragraph("<b>Informação para Zerar Banco de Horas:</b>", styles['h2']))
                    info_text = (f"Para zerar o saldo de BH, o horário de saída no próximo dia útil, desde que seja respeitado o horário de entrada, "
                                 f"(<b>{next_business_day.strftime('%d/%m/%Y')}</b>) deverá ser às <b>{target_exit_time}</b>.")
                    story.append(Paragraph(info_text, styles['Normal']))
                
                except Exception as e:
                    print(f"Erro ao calcular saída para zerar BH (fichado): {e}")
                    story.append(Paragraph("<i>Não foi possível calcular o horário para zerar o BH.</i>", styles['Italic']))
                # --- FIM DA MODIFICAÇÃO ---

                story.append(Spacer(1, 2.5*cm))
                story.append(Paragraph("________________________________________", styles['Normal']))
                story.append(Paragraph(nome, styles['Normal']))
                story.append(Paragraph(f"Data: ____/____/{datetime.now().year}", styles['Normal']))

                doc.build(story)
                messagebox.showinfo("Sucesso", f"Relatório salvo e saldos deduzidos!", parent=win)
                win.destroy()
                self.load_point_viewer(force_reload=True)

            except Exception as e:
                messagebox.showerror("Erro PDF", f"Erro ao gerar PDF: {e}", parent=win)

        def process_fichado_payment():
            matricula = cmb_func.get().split(" - ")[0]
            nome = " ".join(cmb_func.get().split(" - ")[1:])

            try:
                extras_qty_str = data_vars["fichado_info"]['entry_extras_qty'].get()
                extras_valor_str = data_vars["fichado_info"]['entry_extras_valor'].get()

                extras_qty = int(extras_qty_str) if extras_qty_str else 0
                extras_valor = float(extras_valor_str.replace(',', '.')) if extras_valor_str else 0.0

                if extras_qty > 0 and extras_valor <= 0:
                    messagebox.showerror("Erro", "Se a quantidade de extras for maior que zero, o valor unitário também deve ser.", parent=win)
                    return

            except ValueError:
                messagebox.showerror("Erro", "Valores inválidos para Extras (Qtde e Valor). Use apenas números.", parent=win)
                return

            payment_details = {
                'extras_qty': extras_qty,
                'extras_valor': extras_valor,
                'pay_partial_salary': data_vars["partial_salary_var"].get() == "Sim",
                'report_stats': None # <-- MODIFICAÇÃO: Inicializa
            }

            if payment_details['pay_partial_salary']:
                try:
                    salario_mensal_str = data_vars["fichado_info"]['entry_salario_mensal'].get()
                    salario_mensal = float(salario_mensal_str.replace(',', '.')) if salario_mensal_str else 0.0
                    if salario_mensal <= 0:
                        messagebox.showerror("Erro", "Salário mensal deve ser um número positivo.", parent=win)
                        return

                    start_date, end_date = data_vars["fichado_info"]['date_picker'].get_dates()

                    if not start_date or not end_date:
                        messagebox.showerror("Erro", "Datas de início e fim são obrigatórias para salário parcial.", parent=win)
                        return

                    if end_date < start_date:
                        messagebox.showerror("Erro", "Data final não pode ser anterior à data inicial.", parent=win)
                        return

                    if start_date < datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                        messagebox.showerror("Erro", f"Data de início não pode ser anterior a {SYSTEM_START_DATE}.", parent=win)
                        return

                    payment_details['salario_mensal'] = salario_mensal
                    payment_details['start_date'] = start_date
                    payment_details['end_date'] = end_date
                    
                    # --- INÍCIO DA MODIFICAÇÃO (Buscar Estatísticas) ---
                    report_stats = self.db.get_stats_for_period(matricula, start_date, end_date)
                    payment_details['report_stats'] = report_stats
                    # --- FIM DA MODIFICAÇÃO ---


                except ValueError:
                    messagebox.showerror("Erro", "Valor inválido para Salário Mensal. Use apenas números.", parent=win)
                    return
                except Exception as e:
                    messagebox.showerror("Erro Datas", f"Erro ao processar datas: {e}", parent=win)
                    return

            msg_confirm = f"Confirma o pagamento para {nome}?\n"
            if extras_qty > 0:
                msg_confirm += f"- {extras_qty} Extra(s) serão PAGOS e DEDUZIDOS do saldo.\n"
            if payment_details['pay_partial_salary']:
                 msg_confirm += f"- Salário parcial será CALCULADO.\n"

            if not messagebox.askyesno("Confirmar Ação", msg_confirm, parent=win):
                return

            if self.db.update_saldos(matricula, 0, extras_qty):
                func_info_atualizado = self.db.get_funcionario_info(matricula)
                generate_pdf_fichado(matricula, nome, func_info_atualizado, payment_details)
            else:
                messagebox.showerror("Erro DB", "Falha ao atualizar os saldos no banco de dados.", parent=win)

        def generate_pdf_nao_fichado(matricula, nome, func_info, payment_details):
            filepath = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], title="Salvar Relatório de Pagamento", initialfile=f"Pagamento_{nome.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf")
            if not filepath:
                return

            try:
                doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
                styles = getSampleStyleSheet()
                story = []

                style_title = styles['h1']
                style_title.alignment = 1
                style_title.textColor = colors.teal

                style_obs = styles['Italic']
                style_obs.fontSize = 9
                style_obs.textColor = colors.darkred

                if LOGO_PATH.exists():
                    try:
                        story.append(Image(LOGO_PATH, width=4.5*cm, height=4.5*cm, hAlign='CENTER'))
                        story.append(Spacer(1, 0.5*cm))
                    except Exception as e:
                        print(f"Erro ao adicionar logo ao PDF: {e}")

                story.append(Paragraph("Recibo de Pagamento (Diárias)", style_title))
                story.append(Spacer(1, 1*cm))

                story.append(Paragraph(f"<b>Funcionário:</b> {nome}", styles['Normal']))
                story.append(Paragraph(f"<b>Matrícula:</b> {matricula}", styles['Normal']))
                story.append(Paragraph(f"<b>Status:</b> Não Fichado", styles['Normal']))
                story.append(Paragraph(f"<b>Período (Diárias):</b> {payment_details['start_date'].strftime('%d/%m/%Y')} a {payment_details['end_date'].strftime('%d/%m/%Y')}", styles['Normal']))
                story.append(Spacer(1, 1*cm))

                table_data = [['Item', 'Qtde', 'Valor Unitário (R$)', 'Total (R$)']]

                dias_normais = payment_details['dias_normais']
                dias_dobrados = payment_details['dias_dobrados']
                valor_diaria = payment_details['valor_diaria']
                extras_qty = payment_details.get('extras_qty', 0)
                extras_valor = payment_details.get('extras_valor', 0.0)

                total_normais = len(dias_normais) * valor_diaria
                total_dobrados = len(dias_dobrados) * (valor_diaria * 2)
                total_extras_pago = extras_qty * extras_valor
                total_pago = total_normais + total_dobrados + total_extras_pago

                if total_extras_pago > 0:
                    table_data.append(['Pagamento de Extras', f"{extras_qty} un.", f"{extras_valor:.2f}", f"{total_extras_pago:.2f}"])

                table_data.append(['Diárias Normais (Trabalhadas)', f"{len(dias_normais)} dias", f"{valor_diaria:.2f}", f"{total_normais:.2f}"])
                table_data.append(['Diárias Dobradas (Dom/Feriado)', f"{len(dias_dobrados)} dias", f"{valor_diaria * 2:.2f}", f"{total_dobrados:.2f}"])
                table_data.append(['TOTAL PAGO', '', '', f"R$ {total_pago:.2f}"])

                t = Table(table_data, colWidths=[6*cm, 3*cm, 4*cm, 4*cm])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.teal),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0,0), (-1,0), 12),
                    ('BACKGROUND', (0,1), (-1,-2), colors.beige),
                    ('GRID', (0,0), (-1,-1), 1, colors.black),
                    ('BACKGROUND', (0,-1), (-1,-1), colors.darkgrey),
                    ('TEXTCOLOR', (0,-1), (-1,-1), colors.whitesmoke),
                    ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
                ]))
                story.append(t)
                story.append(Spacer(1, 0.5*cm))

                if dias_dobrados:
                    story.append(Paragraph("<b>Observações (Dias Dobrados):</b>", styles['h2']))
                    dias_str = ", ".join([d.strftime('%d/%m') for d in dias_dobrados])
                    story.append(Paragraph(f"Dias com pagamento dobrado: {dias_str}", style_obs))
                    story.append(Spacer(1, 0.5*cm))

                # --- INÍCIO DA MODIFICAÇÃO (Adicionar Estatísticas) ---
                report_stats = payment_details.get('report_stats')
                if report_stats:
                    story.append(Paragraph(f"<b>Estatísticas do Período ({payment_details['start_date'].strftime('%d/%m')} a {payment_details['end_date'].strftime('%d/%m')})</b>", styles['h2']))
                    
                    stats_data = [
                        ['Faltas Totais (dias com 0h):', f"{report_stats['total_absences']} dia(s)"],
                        ['Faltas Parciais (dias < jornada):', f"{report_stats['partial_absences']} dia(s)"],
                        ['Dias com Atraso (desconto):', f"{report_stats['days_with_delay']} dia(s)"],
                        ['Total Descontado (Atrasos):', f"{format_minutes_to_hms(report_stats['total_delay_discount'])}"],
                        ['Punições no Período:', f"{report_stats['punishment_count']}"],
                        ['Total Descontado (Punições):', f"{format_minutes_to_hms(report_stats['total_punishment_discount'])}"]
                    ]
                    
                    stats_table = Table(stats_data, colWidths=[8*cm, 4*cm])
                    stats_table.setStyle(TableStyle([
                        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                        ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
                        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
                        ('FONTSIZE', (0,0), (-1,-1), 9),
                        ('TOPPADDING', (0,0), (-1,-1), 4),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                    ]))
                    story.append(stats_table)
                    story.append(Spacer(1, 1*cm))
                # --- FIM DA MODIFICAÇÃO ---

                story.append(Paragraph("<b>Saldos Remanescentes (Após Pagamento)</b>", styles['h2']))
                story.append(Paragraph(f"<b>Banco de Horas:</b> {format_minutes_to_hms(func_info.get('banco_horas', 0))}", styles['Normal']))
                story.append(Paragraph(f"<b>Extras:</b> {int(func_info.get('extras_disponiveis', 0))}", styles['Normal']))

                # --- INÍCIO DA MODIFICAÇÃO (NÃO FICHADO) ---
                try:
                    remaining_bh = func_info.get('banco_horas', 0)
                    
                    # --- AJUSTE SOLICITADO ---
                    # Para não fichado, a data base é sempre o fim do período de diárias
                    start_search_date = payment_details['end_date']
                    # --- FIM AJUSTE SOLICITADO ---

                    # Esta função é para 'não fichado', então is_fichado=False
                    next_business_day = self.find_next_business_day(start_search_date, is_fichado=False)
                    target_exit_time = self.calculate_bh_zero_exit(remaining_bh, next_business_day)
                    
                    story.append(Spacer(1, 0.5*cm))
                    story.append(Paragraph("<b>Informação para Zerar Banco de Horas:</b>", styles['h2']))
                    info_text = (f"Para zerar o saldo de BH, o horário de saída no próximo dia útil "
                                 f"(<b>{next_business_day.strftime('%d/%m/%Y')}</b>) deverá ser às <b>{target_exit_time}</b>.")
                    story.append(Paragraph(info_text, styles['Normal']))
                
                except Exception as e:
                    print(f"Erro ao calcular saída para zerar BH (não fichado): {e}")
                    story.append(Paragraph("<i>Não foi possível calcular o horário para zerar o BH.</i>", styles['Italic']))
                # --- FIM DA MODIFICAÇÃO ---

                story.append(Spacer(1, 2.5*cm))
                story.append(Paragraph("________________________________________", styles['Normal']))
                story.append(Paragraph(nome, styles['Normal']))
                story.append(Paragraph(f"Data: ____/____/{datetime.now().year}", styles['Normal']))

                doc.build(story)
                messagebox.showinfo("Sucesso", f"Relatório salvo e saldos deduzidos!", parent=win)
                win.destroy()
                self.load_point_viewer(force_reload=True)

            except Exception as e:
                messagebox.showerror("Erro PDF", f"Erro ao gerar PDF: {e}", parent=win)

        def process_nao_fichado_payment():
            matricula = cmb_func.get().split(" - ")[0]
            nome = " ".join(cmb_func.get().split(" - ")[1:])

            try:
                extras_qty_str = data_vars["nao_fichado_info"]['entry_extras_qty'].get()
                extras_valor_str = data_vars["nao_fichado_info"]['entry_extras_valor'].get()

                extras_qty = int(extras_qty_str) if extras_qty_str else 0
                extras_valor = float(extras_valor_str.replace(',', '.')) if extras_valor_str else 0.0

                if extras_qty > 0 and extras_valor <= 0:
                    messagebox.showerror("Erro", "Se a quantidade de extras for maior que zero, o valor unitário também deve ser.", parent=win)
                    return

                valor_diaria_str = data_vars["nao_fichado_info"]['entry_valor_diaria'].get()
                valor_diaria = float(valor_diaria_str.replace(',', '.')) if valor_diaria_str else 0.0

                if valor_diaria <= 0:
                    messagebox.showerror("Erro", "O Valor da Diária deve ser um número positivo.", parent=win)
                    return

                start_date, end_date = data_vars["nao_fichado_info"]['date_picker'].get_dates()

                if not start_date or not end_date or end_date < start_date:
                    messagebox.showerror("Erro", "Período inválido para as diárias.", parent=win)
                    return

                if start_date < datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                    messagebox.showerror("Erro", f"Data de início não pode ser anterior a {SYSTEM_START_DATE}.", parent=win)
                    return

            except ValueError:
                messagebox.showerror("Erro", "Valores inválidos para Extras ou Diária. Use apenas números.", parent=win)
                return
            except Exception as e:
                messagebox.showerror("Erro Datas", f"Erro ao processar datas: {e}", parent=win)
                return

            try:
                worked_days = self.db.get_worked_days_in_range(matricula, start_date, end_date)

                dias_normais = []
                dias_dobrados = []

                for dia in worked_days:
                    if is_sunday_or_holiday(dia):
                        dias_dobrados.append(dia)
                    else:
                        dias_normais.append(dia)

                total_diarias = (len(dias_normais) * valor_diaria) + (len(dias_dobrados) * valor_diaria * 2)
                total_extras = extras_qty * extras_valor
                total_payment = total_diarias + total_extras
                
                # --- INÍCIO DA MODIFICAÇÃO (Buscar Estatísticas) ---
                report_stats = self.db.get_stats_for_period(matricula, start_date, end_date)
                # --- FIM DA MODIFICAÇÃO ---

                msg_confirm = (f"Pagamento para {nome} (Não Fichado):\n\n"
                               f"--- Extras ---\n"
                               f"Qtde: {extras_qty} un. (R$ {total_extras:.2f})\n\n"
                               f"--- Diárias (Dias Trabalhados) ---\n"
                               f"Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}\n"
                               f"Dias Normais: {len(dias_normais)} (R$ {len(dias_normais) * valor_diaria:.2f})\n"
                               f"Dias Dobrados: {len(dias_dobrados)} (R$ {len(dias_dobrados) * valor_diaria * 2:.2f})\n\n"
                               f"TOTAL A PAGAR: R$ {total_payment:.2f}\n\n"
                               f"Confirma a geração do relatório e DEDUÇÃO DAS EXTRAS?")

                if not messagebox.askyesno("Confirmar Pagamento", msg_confirm, parent=win):
                    return

                payment_details = {
                    'start_date': start_date,
                    'end_date': end_date,
                    'valor_diaria': valor_diaria,
                    'dias_normais': dias_normais,
                    'dias_dobrados': dias_dobrados,
                    'extras_qty': extras_qty,
                    'extras_valor': extras_valor,
                    'report_stats': report_stats # <-- MODIFICAÇÃO: Adiciona stats
                }

                if self.db.update_saldos(matricula, 0, extras_qty):
                    func_info_atualizado = self.db.get_funcionario_info(matricula)
                    generate_pdf_nao_fichado(matricula, nome, func_info_atualizado, payment_details)
                else:
                    messagebox.showerror("Erro DB", "Falha ao atualizar os saldos no banco de dados.", parent=win)

            except Exception as e:
                messagebox.showerror("Erro Cálculo", f"Erro ao calcular dias trabalhados: {e}", parent=win)

        def setup_fichado_ui(func_info):
            frame_saldos = ttk.LabelFrame(details_frame, text=" Saldos Atuais ", style='TLabelframe')
            frame_saldos.pack(fill='x', pady=10)

            lbl_saldo_bh = tk.Label(frame_saldos, text=f"BH: {format_minutes_to_hms(func_info.get('banco_horas', 0))}", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"))
            lbl_saldo_bh.pack(side=tk.LEFT, padx=10, pady=5)

            lbl_saldo_extras = tk.Label(frame_saldos, text=f"Extras: {int(func_info.get('extras_disponiveis', 0))} un.", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"))
            lbl_saldo_extras.pack(side=tk.LEFT, padx=10, pady=5)

            frame_extras = ttk.LabelFrame(details_frame, text=" Pagamento de Extras ", style='TLabelframe')
            frame_extras.pack(fill='x', pady=5)

            tk.Label(frame_extras, text="Qtde Extras a Pagar:", bg=self.BG_COLOR, fg=self.FG_COLOR).grid(row=0, column=0, padx=5, pady=5, sticky='w')
            entry_extras_qty = ttk.Entry(frame_extras, width=10)
            entry_extras_qty.grid(row=0, column=1, padx=5, pady=5)

            tk.Label(frame_extras, text="Valor Unitário (R$):", bg=self.BG_COLOR, fg=self.FG_COLOR).grid(row=0, column=2, padx=5, pady=5, sticky='w')
            entry_extras_valor = ttk.Entry(frame_extras, width=10)
            entry_extras_valor.grid(row=0, column=3, padx=5, pady=5)

            data_vars["fichado_info"]['entry_extras_qty'] = entry_extras_qty
            data_vars["fichado_info"]['entry_extras_valor'] = entry_extras_valor

            frame_parcial_group = ttk.LabelFrame(details_frame, text=" Pagamento de Salário Parcial ", style='TLabelframe')
            frame_parcial_group.pack(fill='x', pady=10)

            chk_partial_salary = ttk.Checkbutton(frame_parcial_group, text="Pagar Salário Parcial?", variable=data_vars["partial_salary_var"], onvalue="Sim", offvalue="Não")
            chk_partial_salary.pack(anchor='w', padx=5, pady=5)

            frame_parcial_widgets = tk.Frame(frame_parcial_group, bg=self.BG_COLOR)

            # Usa construtor padrão do DateRangePicker
            date_picker = DateRangePicker(frame_parcial_widgets, self.BG_COLOR, self.style_colors_dict)
            date_picker.pack(pady=10)
            # Removida adição à lista dinâmica


            tk.Label(frame_parcial_widgets, text="Valor Salário Mensal (R$):", bg=self.BG_COLOR, fg=self.FG_COLOR).pack(anchor='w', padx=5, pady=(10,0))
            entry_salario_mensal = ttk.Entry(frame_parcial_widgets, width=20)
            entry_salario_mensal.pack(anchor='w', padx=5, pady=5)

            data_vars["fichado_info"]['date_picker'] = date_picker
            data_vars["fichado_info"]['entry_salario_mensal'] = entry_salario_mensal

            def toggle_partial_salary_widgets(*args):
                if data_vars["partial_salary_var"].get() == "Sim":
                    frame_parcial_widgets.pack(fill='x', pady=5)
                else:
                    frame_parcial_widgets.pack_forget()

            data_vars["partial_salary_var"].trace("w", toggle_partial_salary_widgets)
            toggle_partial_salary_widgets()

            btn_process = ttk.Button(details_frame, text="Gerar Relatório e Deduzir Extras", style='TButton', command=process_fichado_payment)
            btn_process.pack(pady=20)

        def setup_nao_fichado_ui(func_info):
            frame_saldos = ttk.LabelFrame(details_frame, text=" Saldos Atuais ", style='TLabelframe')
            frame_saldos.pack(fill='x', pady=10)

            lbl_saldo_bh = tk.Label(frame_saldos, text=f"BH: {format_minutes_to_hms(func_info.get('banco_horas', 0))}", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"))
            lbl_saldo_bh.pack(side=tk.LEFT, padx=10, pady=5)

            lbl_saldo_extras = tk.Label(frame_saldos, text=f"Extras: {int(func_info.get('extras_disponiveis', 0))} un.", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"))
            lbl_saldo_extras.pack(side=tk.LEFT, padx=10, pady=5)

            frame_extras = ttk.LabelFrame(details_frame, text=" Pagamento de Extras ", style='TLabelframe')
            frame_extras.pack(fill='x', pady=5)

            tk.Label(frame_extras, text="Qtde Extras a Pagar:", bg=self.BG_COLOR, fg=self.FG_COLOR).grid(row=0, column=0, padx=5, pady=5, sticky='w')
            entry_extras_qty = ttk.Entry(frame_extras, width=10)
            entry_extras_qty.grid(row=0, column=1, padx=5, pady=5)

            tk.Label(frame_extras, text="Valor Unitário (R$):", bg=self.BG_COLOR, fg=self.FG_COLOR).grid(row=0, column=2, padx=5, pady=5, sticky='w')
            entry_extras_valor = ttk.Entry(frame_extras, width=10)
            entry_extras_valor.grid(row=0, column=3, padx=5, pady=5)

            data_vars["nao_fichado_info"]['entry_extras_qty'] = entry_extras_qty
            data_vars["nao_fichado_info"]['entry_extras_valor'] = entry_extras_valor

            frame_diarias = ttk.LabelFrame(details_frame, text=" Pagamento de Diárias (Dias Trabalhados) ", style='TLabelframe')
            frame_diarias.pack(fill='x', pady=10)

            # Usa construtor padrão do DateRangePicker
            date_picker = DateRangePicker(frame_diarias, self.BG_COLOR, self.style_colors_dict)
            date_picker.pack(pady=10)
            # Removida adição à lista dinâmica


            tk.Label(frame_diarias, text="Valor da Diária (R$):", bg=self.BG_COLOR, fg=self.FG_COLOR).pack(anchor='w', padx=5, pady=(10,0))
            entry_valor_diaria = ttk.Entry(frame_diarias, width=20)
            entry_valor_diaria.pack(anchor='w', padx=5, pady=5)

            data_vars["nao_fichado_info"]['date_picker'] = date_picker
            data_vars["nao_fichado_info"]['entry_valor_diaria'] = entry_valor_diaria

            btn_process = ttk.Button(details_frame, text="Calcular e Gerar Relatório", style='TButton', command=process_nao_fichado_payment)
            btn_process.pack(pady=20)

        def on_employee_select(event=None):
            selection = cmb_func.get()
            if not selection:
                return

            clear_details_frame()
            matricula = selection.split(" - ")[0]
            func_info = self.db.get_funcionario_info(matricula)

            if func_info.get('fichado', 0) == 1:
                setup_fichado_ui(func_info)
            else:
                setup_nao_fichado_ui(func_info)

        cmb_func.bind("<<ComboboxSelected>>", on_employee_select)


    def on_export_log(self, *args):
        win = tk.Toplevel(self.root); win.title("Exportar Log")
        win.configure(bg="#0a192f"); win.state('zoomed'); win.minsize(800, 450)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg="#0a192f")
        main_frame.pack(expand=True)

        form_frame = tk.Frame(main_frame, bg="#0a192f", padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy, width=10).pack(anchor='e', pady=(0,10))

        tk.Label(form_frame, text="1. Func:", bg="#0a192f", fg="#ccd6f6", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]; cmb_func = ttk.Combobox(form_frame, values=nomes, state="readonly", width=50); cmb_func.pack(anchor="w", pady=(0, 20)); tk.Label(form_frame, text="2. Período:", bg="#0a192f", fg="#ccd6f6", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))

        try:
            min_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        except:
            min_date = None

        period_frame = tk.Frame(form_frame, bg="#0a1f2f"); period_frame.pack(anchor="w"); tk.Label(period_frame, text="De:", bg="#0a192f", fg="#ccd6f6").pack(side=tk.LEFT, padx=(0,5)); cal_start = Calendar(period_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080", mindate=min_date); cal_start.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(period_frame, text="Até:", bg="#0a192f", fg="#ccd6f6").pack(side=tk.LEFT, padx=(0,5)); cal_end = Calendar(period_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080", mindate=min_date); cal_end.pack(side=tk.LEFT); btn_export = ttk.Button(form_frame, text="Gerar PDF", style='TButton'); btn_export.pack(pady=20)
        
        # Removida adição à lista dinâmica


        if min_date:
            cal_start.selection_set(max(date.today().replace(day=1), min_date))
        else:
            cal_start.selection_set(date.today().replace(day=1))

        def generate_pdf():
            selection = cmb_func.get();
            if not selection: messagebox.showerror("Erro", "Funcionário não selecionado.", parent=win); return
            matricula = selection.split(" - ")[0]; nome_func = " ".join(selection.split(" - ")[1:])
            start_date_str = cal_start.get_date(); end_date_str = cal_end.get_date()

            try:
                start_dt = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_dt = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if end_dt < start_dt:
                    messagebox.showerror("Erro", "Data final não pode ser anterior à data inicial.", parent=win)
                    return
                if start_dt < datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                    messagebox.showerror("Erro", f"Data de início não pode ser anterior a {SYSTEM_START_DATE}.", parent=win)
                    return
            except Exception as e:
                messagebox.showerror("Erro", f"Datas inválidas: {e}", parent=win)
                return

            logs = self.db.get_logs_for_period(matricula, start_date_str, end_date_str)
            if not logs: messagebox.showinfo("Aviso", "Nenhum log encontrado.", parent=win); return

            filepath = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], title="Salvar Relatório", initialfile=f"Log_{nome_func.replace(' ','_')}_{start_date_str}_a_{end_date_str}.pdf")
            if not filepath: return
            try:
                doc = SimpleDocTemplate(filepath, pagesize=landscape(A4), rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm); styles = getSampleStyleSheet(); story = []
                story.append(Paragraph("Relatório Log Alterações", styles['h1'])); story.append(Spacer(1, 0.5*cm)); story.append(Paragraph(f"<b>Funcionário:</b> {nome_func}", styles['Normal'])); story.append(Paragraph(f"<b>Matrícula:</b> {matricula}", styles['Normal'])); story.append(Paragraph(f"<b>Período:</b> {start_dt.strftime('%d/%m/%Y')} a {end_dt.strftime('%d/%m/%Y')}", styles['Normal'])); story.append(Spacer(1, 1*cm))
                table_data = [['Data Ponto', 'Data Edição', 'Valor Antigo', 'Valor Novo', 'Justificativa']]; [table_data.append([datetime.strptime(log['data_ponto'], '%Y-%m-%d').strftime('%d/%m/%Y'), datetime.strptime(log['data_edicao'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M'), log['periodos_antigos'], log['periodos_novos'], log['justificativa']]) for log in logs]
                t = Table(table_data, colWidths=[2.5*cm, 3.0*cm, 8.0*cm, 8.0*cm, 4.0*cm]); t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.teal), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0,0), (-1,0), 12), ('BACKGROUND', (0,1), (-1,-1), colors.beige), ('GRID', (0,0), (-1,-1), 1, colors.black)]))
                story.append(t); doc.build(story); messagebox.showinfo("Sucesso", f"Relatório salvo:\n{filepath}", parent=win); win.destroy()
            except Exception as e: messagebox.showerror("Erro PDF", f"Erro: {e}", parent=win)
        btn_export.config(command=generate_pdf)

    # --- INÍCIO DAS NOVAS FUNÇÕES ---
    def find_next_business_day(self, start_date, is_fichado):
        """Encontra o próximo dia útil (não-domingo, não-feriado se fichado)."""
        current_date = start_date + timedelta(days=1)
        while True:
            weekday = current_date.weekday()
            
            # 1. Domingo NUNCA é dia útil
            if weekday == 6:
                current_date += timedelta(days=1)
                continue

            # 2. Verifica Feriado
            is_holiday = self.db.is_holiday(current_date.isoformat())
            
            # 3. Se Fichado e Feriado, NÃO é dia útil
            if is_fichado and is_holiday:
                current_date += timedelta(days=1)
                continue
                
            # 4. Se chegou aqui, é um dia útil (Sábado é dia útil, Feriado para não-fichado é dia útil)
            return current_date

    def calculate_bh_zero_exit(self, remaining_bh_minutes, next_business_day):
        """Calcula o horário de saída no próximo dia útil para zerar o BH."""
        
        weekday = next_business_day.weekday()
        
        # Define o horário normal de saída
        if weekday == 5: # Sábado (jornada de 4h)
            # Assumindo 07:30 - 11:30
            normal_exit_time = datetime.combine(next_business_day, time(11, 30))
        else: # Seg-Sex (jornada de 8h)
            # Assumindo 07:30-11:30 (4h) e 13:00-17:00 (4h) -> Saída 17:00
            normal_exit_time = datetime.combine(next_business_day, time(17, 0))
            
        # Calcula o horário de saída ajustado
        # Se BH > 0 (crédito), sai mais cedo (subtrai)
        # Se BH < 0 (débito), sai mais tarde (soma)
        target_exit_time = normal_exit_time - timedelta(minutes=remaining_bh_minutes)
        
        return target_exit_time.strftime('%H:%M')
    # --- FIM DAS NOVAS FUNÇÕES ---

    def on_edit_initial_balance(self):
        win = tk.Toplevel(self.root); win.title("Editar Saldos Iniciais")
        win.configure(bg=self.BG_COLOR); win.state('zoomed'); win.minsize(600, 600)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR)
        main_frame.pack(expand=True)
        form_frame = tk.Frame(main_frame, bg=self.BG_COLOR, padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy, width=10).pack(anchor='e', pady=(0,10))

        tk.Label(form_frame, text="1. Func:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); 
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]; 
        cmb_func = ttk.Combobox(form_frame, values=nomes, state="readonly", width=50); 
        cmb_func.pack(anchor="w", pady=(0, 15))

        details_frame = tk.Frame(form_frame, bg=self.BG_COLOR)
        details_frame.pack(fill='x', pady=10)

        lbl_bh_atual = tk.Label(details_frame, text="BH Inicial Atual: --", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10))
        lbl_bh_atual.pack(anchor="w", pady=2)
        lbl_extras_atual = tk.Label(details_frame, text="Extras Iniciais Atuais: --", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10))
        lbl_extras_atual.pack(anchor="w", pady=(0, 10))

        tk.Label(details_frame, text="Novo BH Inicial (HH:MM):", bg=self.BG_COLOR, fg=self.HIGHLIGHT_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(5, 5)); 
        entry_bh = ttk.Entry(details_frame, width=15); 
        entry_bh.pack(anchor="w", pady=(0, 15))

        tk.Label(details_frame, text="Novas Extras Iniciais (Un):", bg=self.BG_COLOR, fg=self.HIGHLIGHT_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); 
        entry_extras = ttk.Entry(details_frame, width=15); 
        entry_extras.pack(anchor="w", pady=(0, 15))
        
        btn_salvar = ttk.Button(details_frame, text="✅ Salvar e Recalcular", style='TButton', state="disabled")
        btn_salvar.pack(pady=20)

        def on_employee_select(event=None):
            selection = cmb_func.get()
            if not selection: 
                btn_salvar.config(state="disabled")
                return
            
            matricula = selection.split(" - ")[0]
            func_info = self.db.get_funcionario_info(matricula)
            
            bh_inicial_atual = func_info.get('banco_horas_inicial', 0)
            extras_inicial_atual = func_info.get('extras_disponiveis_inicial', 0)

            lbl_bh_atual.config(text=f"BH Inicial Atual: {format_minutes_to_hms(bh_inicial_atual)}")
            lbl_extras_atual.config(text=f"Extras Iniciais Atuais: {int(extras_inicial_atual)}")
            
            entry_bh.delete(0, tk.END)
            entry_bh.insert(0, format_minutes_to_hms(bh_inicial_atual).rsplit(':', 1)[0]) # Insere HH:MM
            
            entry_extras.delete(0, tk.END)
            entry_extras.insert(0, str(int(extras_inicial_atual)))
            
            btn_salvar.config(state="normal")

        def save_initial_balance():
            selection = cmb_func.get()
            if not selection:
                messagebox.showerror("Erro", "Nenhum funcionário selecionado.", parent=win)
                return
            
            matricula = selection.split(" - ")[0]
            nome = " ".join(selection.split(" - ")[1:])
            
            bh_str = entry_bh.get()
            extras_str = entry_extras.get()

            try:
                bh_minutos = parse_hhmm_to_minutes(bh_str)
            except Exception:
                messagebox.showerror("Erro", "Formato de BH Inicial inválido. Use HH:MM.", parent=win)
                return

            try:
                extras_int = int(extras_str)
            except ValueError:
                messagebox.showerror("Erro", "Formato de Extras Iniciais inválido. Use apenas números.", parent=win)
                return

            confirm_msg = f"Atualizar saldos iniciais de {nome}?\n\nNovo BH: {format_minutes_to_hms(bh_minutos)}\nNovas Extras: {extras_int}\n\nATENÇÃO: O saldo ATUAL será recalculado."
            if not messagebox.askyesno("Confirmar Alteração", confirm_msg, parent=win):
                return

            try:
                if self.db.update_initial_balances(matricula, bh_minutos, extras_int):
                    self.append_log(f"Saldos iniciais de {matricula} atualizados. Recalculando...")
                    self.db.recalculate_full_balance_for_employee(matricula)
                    self.append_log(f"Recálculo de {matricula} concluído.")
                    messagebox.showinfo("Sucesso", "Saldos iniciais atualizados e saldo total recalculado!", parent=win)
                    self.load_point_viewer(force_reload=True)
                    win.destroy()
                else:
                    messagebox.showerror("Erro", "Falha ao salvar no banco de dados.", parent=win)
            except Exception as e:
                messagebox.showerror("Erro", f"Erro ao recalcular: {e}", parent=win)
                self.append_log(f"ERRO ao recalcular {matricula} após ajuste inicial: {e}")

        cmb_func.bind("<<ComboboxSelected>>", on_employee_select)
        btn_salvar.config(command=save_initial_balance)

    def on_abone_falta(self):
        win = tk.Toplevel(self.root); win.title("Abonar Faltas/Dias")
        win.configure(bg=self.BG_COLOR); win.state('zoomed'); win.minsize(1024, 768)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        form_frame = ttk.LabelFrame(main_frame, text=" Adicionar Abono ", style='TLabelframe')
        form_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        tk.Label(form_frame, text="1. Func:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 5), padx=10)
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]
        cmb_func = ttk.Combobox(form_frame, values=nomes, state="readonly", width=40)
        cmb_func.pack(anchor="w", pady=(0, 15), padx=10)

        try:
            min_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        except:
            min_date = None

        tk.Label(form_frame, text="2. Data:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        cal_abono = Calendar(form_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR',
                               background="#008080", foreground="white", headersbackground="#008080",
                               mindate=min_date)
        cal_abono.pack(anchor="w", pady=(0, 15), padx=10)

        tk.Label(form_frame, text="3. Tempo a Abonar (HH:MM):", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        entry_tempo = ttk.Entry(form_frame, width=15)
        entry_tempo.pack(anchor="w", padx=10, pady=(0, 15))

        tk.Label(form_frame, text="4. Motivo:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        entry_motivo = ttk.Entry(form_frame, width=30)
        entry_motivo.pack(anchor="w", fill="x", pady=(0, 15), padx=10)
        entry_motivo.insert(0, "Atestado Médico")

        btn_save = ttk.Button(form_frame, text="✅ Salvar Abono e Recalcular", style='TButton')
        btn_save.pack(pady=10, padx=10, fill=tk.X)

        btn_delete = ttk.Button(form_frame, text="🗑️ Remover Abono Selecionado", style='Delete.TButton')
        btn_delete.pack(pady=(15, 5), padx=10, fill=tk.X)

        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy).pack(side=tk.BOTTOM, pady=10, padx=10, fill=tk.X)

        list_frame = ttk.LabelFrame(main_frame, text=" Abonos Registrados (no período) ", style='TLabelframe')
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        tree_columns = ("Data", "Tempo Abonado", "Motivo") # <-- COLUNA ATUALIZADA
        tree_abonos = ttk.Treeview(list_frame, columns=tree_columns, show="headings", selectmode="browse")

        v_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree_abonos.yview)
        tree_abonos.configure(yscrollcommand=v_scroll.set)
        tree_abonos.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')

        tree_abonos.heading("Data", text="Data")
        tree_abonos.column("Data", width=100, anchor=tk.CENTER)
        tree_abonos.heading("Tempo Abonado", text="Tempo Abonado") # <-- COLUNA ATUALIZADA
        tree_abonos.column("Tempo Abonado", width=110, anchor=tk.CENTER) # <-- COLUNA ATUALIZADA
        tree_abonos.heading("Motivo", text="Motivo")
        tree_abonos.column("Motivo", width=250, anchor=tk.W, stretch=tk.YES)

        def _update_abono_time(event=None):
            """Preenche o tempo padrão (8h ou 4h) baseado no dia da semana."""
            try:
                selected_date = cal_abono.selection_get()
                if not selected_date:
                    return
                
                # Sábado = 4h
                if selected_date.weekday() == 5:
                    default_minutes = MINUTOS_JORNADA_SABADO
                # Domingo ou Feriado (para fichado) = 0h, mas deixamos 8h como padrão
                # elif selected_date.weekday() == 6:
                #     default_minutes = 0
                # Seg-Sex = 8h
                else:
                    default_minutes = MINUTOS_JORNADA_SEG_SEX
                
                entry_tempo.delete(0, tk.END)
                entry_tempo.insert(0, format_minutes_to_hms(default_minutes).rsplit(':', 1)[0]) # Insere HH:MM

            except Exception as e:
                print(f"Erro ao auto-preencher tempo: {e}")

        cal_abono.bind("<<CalendarSelected>>", _update_abono_time)
        _update_abono_time() # Chama uma vez para preencher o valor inicial

        def refresh_abono_list():
            [tree_abonos.delete(i) for i in tree_abonos.get_children()]
            selection = cmb_func.get()
            if not selection:
                return
            
            matricula = selection.split(" - ")[0]
            start_date = self.selected_start_date
            end_date = self.selected_end_date
            
            if not start_date or not end_date:
                start_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
                end_date = date.today()

            abonos = self.db.get_abonos_in_range(matricula, start_date, end_date)
            for i, abono in enumerate(abonos):
                try:
                    data_fmt = datetime.strptime(abono['data'], '%Y-%m-%d').strftime('%d/%m/%Y')
                except:
                    data_fmt = abono['data']
                
                # <-- VALORES ATUALIZADOS -->
                minutos_abonados = abono.get('minutos_abonados', 0)
                values = (data_fmt, format_minutes_to_hms(minutos_abonados), abono['motivo'])
                # <-- FIM DA ATUALIZAÇÃO -->

                iid = f"abono_{abono['id']}"
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree_abonos.insert("", "end", values=values, iid=iid, tags=(tag,))

        def save_abono():
            selection = cmb_func.get()
            if not selection: 
                messagebox.showerror("Erro", "Selecione um funcionário.", parent=win)
                return
            
            matricula = selection.split(" - ")[0]
            nome = " ".join(selection.split(" - ")[1:])
            
            try:
                data_dt = cal_abono.selection_get()
                date_str = data_dt.isoformat()
            except:
                messagebox.showerror("Erro", "Data inválida.", parent=win)
                return
            
            motivo = entry_motivo.get().strip()
            if not motivo:
                messagebox.showerror("Erro", "Motivo é obrigatório.", parent=win)
                return
                
            # <-- LÓGICA DE TEMPO ADICIONADA -->
            tempo_str = entry_tempo.get().strip()
            minutos_abonados = parse_hhmm_to_minutes(tempo_str)
            if minutos_abonados <= 0:
                messagebox.showerror("Erro", "Tempo a abonar inválido ou zero. Use o formato HH:MM.", parent=win)
                return
            # <-- FIM DA ADIÇÃO -->
            
            if date_str < SYSTEM_START_DATE:
                 messagebox.showerror("Erro", f"Não é possível abonar dias antes de {SYSTEM_START_DATE}.", parent=win)
                 return

            confirm_msg = f"Confirmar abono de {format_minutes_to_hms(minutos_abonados)} para {nome} em {data_dt.strftime('%d/%m/%Y')}?\nMotivo: {motivo}\n\nO saldo será recalculado."
            if not messagebox.askyesno("Confirmar Abono", confirm_msg, parent=win):
                return
            
            if self.db.add_abono(matricula, date_str, motivo, minutos_abonados): # <-- PARÂMETRO ADICIONADO
                self.append_log(f"ABONO REGISTRADO: {matricula} - {date_str} - {format_minutes_to_hms(minutos_abonados)} - {motivo}. Recalculando...")
                try:
                    self.db.recalculate_full_balance_for_employee(matricula)
                    self.append_log(f"Recálculo de {matricula} concluído.")
                    messagebox.showinfo("Sucesso", "Abono salvo e saldo recalculado!", parent=win)
                    refresh_abono_list()
                    self.load_point_viewer(force_reload=True)
                except Exception as e:
                    messagebox.showerror("Erro", f"Erro ao recalcular: {e}", parent=win)
                    self.append_log(f"ERRO ao recalcular {matricula} após abono: {e}")
            else:
                messagebox.showerror("Erro", "Falha ao salvar abono no banco de dados.", parent=win)

        def delete_abono():
            selected_iid = tree_abonos.selection()
            if not selected_iid:
                messagebox.showerror("Erro", "Nenhum abono selecionado na lista.", parent=win)
                return

            iid = selected_iid[0]
            if not iid.startswith('abono_'):
                return
                
            item_data = tree_abonos.item(iid, 'values')
            desc = f"{item_data[0]} ({item_data[1]}) - {item_data[2]}" # <-- ATUALIZADO
            abono_id = iid.split('_')[1]

            if not messagebox.askyesno("Confirmar Remoção", f"Tem certeza que deseja remover o abono:\n{desc}\n\nO saldo será recalculado.", parent=win):
                return

            matricula_afetada = self.db.delete_abono(abono_id)
            if matricula_afetada:
                self.append_log(f"ABONO REMOVIDO: {desc}. Recalculando...")
                try:
                    self.db.recalculate_full_balance_for_employee(matricula_afetada)
                    self.append_log(f"Recálculo de {matricula_afetada} concluído.")
                    messagebox.showinfo("Sucesso", "Abono removido e saldo recalculado!", parent=win)
                    refresh_abono_list()
                    self.load_point_viewer(force_reload=True)
                except Exception as e:
                    messagebox.showerror("Erro", f"Erro ao recalcular: {e}", parent=win)
                    self.append_log(f"ERRO ao recalcular {matricula_afetada} após remover abono: {e}")
            else:
                messagebox.showerror("Erro", "Não foi possível remover o abono.", parent=win)

        cmb_func.bind("<<ComboboxSelected>>", lambda e: refresh_abono_list())
        btn_save.config(command=save_abono)
        btn_delete.config(command=delete_abono)
        
        if self.cmb_filter_func.get() and self.cmb_filter_func.get() != "Todos":
            cmb_func.set(self.cmb_filter_func.get())
            refresh_abono_list()

    def on_detailed_report(self):
        win = tk.Toplevel(self.root); win.title("Relatório Detalhado")
        win.configure(bg=self.BG_COLOR); win.state('zoomed'); win.minsize(1024, 768)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        form_frame = ttk.LabelFrame(main_frame, text=" Selecionar Período e Funcionário ", style='TLabelframe')
        form_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(form_frame, text="1. Func:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 5), padx=10)
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]
        cmb_func = ttk.Combobox(form_frame, values=nomes, state="readonly", width=50)
        cmb_func.pack(anchor="w", pady=(0, 15), padx=10)
        
        if self.cmb_filter_func.get() and self.cmb_filter_func.get() != "Todos":
            cmb_func.set(self.cmb_filter_func.get())

        tk.Label(form_frame, text="2. Período:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        
        date_picker = DateRangePicker(form_frame, self.BG_COLOR, self.style_colors_dict)
        date_picker.pack(pady=10, padx=10)
        
        if self.selected_start_date:
            date_picker.cal.selection_set(self.selected_start_date)
            date_picker._on_calendar_click()
        if self.selected_end_date:
            date_picker.cal.selection_set(self.selected_end_date)
            date_picker._on_calendar_click()

        btn_generate = ttk.Button(form_frame, text="Gerar PDF", style='TButton')
        btn_generate.pack(pady=20, padx=10)
        
        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy).pack(side=tk.BOTTOM, pady=10, padx=10)

        def generate_report():
            selection = cmb_func.get()
            if not selection:
                messagebox.showerror("Erro", "Selecione um funcionário.", parent=win)
                return
                
            matricula = selection.split(" - ")[0]
            nome = " ".join(selection.split(" - ")[1:])
            
            start_date, end_date = date_picker.get_dates()
            if not start_date or not end_date or end_date < start_date:
                messagebox.showerror("Erro", "Selecione um período válido (Início e Fim).", parent=win)
                return

            try:
                self.append_log(f"Gerando relatório detalhado para {matricula} de {start_date} a {end_date}...")
                stats = self.db.get_detailed_stats_for_period(matricula, start_date, end_date)
                self.append_log("Estatísticas calculadas.")
            except Exception as e:
                messagebox.showerror("Erro no Cálculo", f"Não foi possível calcular as estatísticas:\n{e}", parent=win)
                self.append_log(f"ERRO ao gerar relatório detalhado: {e}")
                return

            filepath = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")],
                title="Salvar Relatório Detalhado",
                initialfile=f"Relatorio_{nome.replace(' ','_')}_{start_date.isoformat()}_a_{end_date.isoformat()}.pdf"
            )
            if not filepath:
                return

            try:
                doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
                styles = getSampleStyleSheet()
                story = []

                if LOGO_PATH.exists():
                    story.append(Image(LOGO_PATH, width=3*cm, height=3*cm, hAlign='CENTER'))
                    story.append(Spacer(1, 0.2*cm))

                story.append(Paragraph("Relatório Detalhado de Ponto", styles['h1']))
                story.append(Spacer(1, 1*cm))
                
                story.append(Paragraph(f"<b>Funcionário:</b> {stats['nome']} (Mat. {stats['matricula']})", styles['Normal']))
                story.append(Paragraph(f"<b>Período:</b> {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}", styles['Normal']))
                story.append(Spacer(1, 1*cm))

                # --- Tabela de Resumo ---
                story.append(Paragraph("Resumo do Período", styles['h2']))
                
                resumo_data = [
                    ['Dias Trabalhados', f"{stats['dias_trabalhados']}"],
                    ['Faltas (Não Abonadas)', f"{stats['faltas_nao_abonadas']}"],
                    ['Faltas (Abonadas)', f"{stats['faltas_abonadas']}"],
                    ['Total de Minutos Abonados', f"{format_minutes_to_hms(stats['minutos_abonados_total'])}"], # <-- LINHA ADICIONADA
                    ['Dias com Atraso (desconto)', f"{stats['dias_com_atraso']}"],
                    ['Total Deduzido (Atrasos)', f"{format_minutes_to_hms(stats['atrasos_deduzidos_min'])}"],
                    ['Punições no Período', f"{stats['punicoes_count']}"],
                    ['Total Deduzido (Punições)', f"{format_minutes_to_hms(stats['punicoes_min'])}"],
                ]
                
                t_resumo = Table(resumo_data, colWidths=[8*cm, 4*cm])
                t_resumo.setStyle(TableStyle([
                    ('GRID', (0,0), (-1,-1), 1, colors.grey),
                    ('BACKGROUND', (0,0), (0,-1), colors.lightgrey),
                    ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
                    ('ALIGN', (1,0), (1,-1), 'CENTER'),
                ]))
                story.append(t_resumo)
                story.append(Spacer(1, 1*cm))
                
                # --- Tabela de Saldos ---
                story.append(Paragraph("Evolução dos Saldos", styles['h2']))
                
                saldo_data = [
                    ['Item', f"Em {start_date.strftime('%d/%m/%Y')} (Início)", f"Em {end_date.strftime('%d/%m/%Y')} (Fim)", 'Variação no Período'],
                    ['Banco de Horas', 
                        format_minutes_to_hms(stats['bh_start']), 
                        format_minutes_to_hms(stats['bh_end']), 
                        format_minutes_to_hms(stats['bh_end'] - stats['bh_start'])],
                    ['Extras Disponíveis', 
                        f"{int(stats['extras_start'])} un.", 
                        f"{int(stats['extras_end'])} un.", 
                        f"{int(stats['extras_geradas_periodo'])} un."]
                ]
                
                t_saldos = Table(saldo_data, colWidths=[4*cm, 4.5*cm, 4.5*cm, 4*cm])
                t_saldos.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.teal),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('GRID', (0,0), (-1,-1), 1, colors.black),
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                    ('BACKGROUND', (0,1), (-1,-1), colors.beige),
                ]))
                story.append(t_saldos)
                story.append(Spacer(1, 2.5*cm))

                story.append(Paragraph("________________________________________", styles['Normal']))
                story.append(Paragraph(stats['nome'], styles['Normal']))
                story.append(Paragraph(f"Data: ____/____/{datetime.now().year}", styles['Normal']))

                doc.build(story)
                messagebox.showinfo("Sucesso", f"Relatório salvo com sucesso!", parent=win)
                self.append_log("Relatório PDF gerado.")
                win.destroy()

            except PermissionError:
                 messagebox.showerror("Erro", f"Erro de Permissão.\nO arquivo '{filepath}' pode estar aberto. Feche-o e tente novamente.", parent=win)
            except Exception as e:
                messagebox.showerror("Erro PDF", f"Não foi possível gerar o PDF: {e}", parent=win)
                self.append_log(f"ERRO PDF: {e}")

        btn_generate.config(command=generate_report)

    def on_recalculate_and_refresh(self):
        """
        Força o recálculo do saldo para o(s) funcionário(s) selecionado(s)
        e depois atualiza o panorama.
        """
        self.append_log("Iniciando recálculo manual de saldos...")
        target_matricula_str = self.cmb_filter_func.get()
        recalc_errors = 0

        if target_matricula_str == "Todos":
            if not messagebox.askyesno("Confirmar Recálculo Total", "Isso irá recalcular o saldo para TODOS os funcionários. Pode demorar.\n\nDeseja continuar?"):
                self.append_log("Recálculo cancelado pelo usuário.")
                return
            all_employees = self.db.get_all_funcionarios()
            self.append_log(f"Recalculando {len(all_employees)} funcionários...")
            for emp in all_employees:
                try:
                    self.db.recalculate_full_balance_for_employee(emp['matricula'])
                except Exception as e:
                   self.append_log(f"ERRO ao recalcular saldo para {emp['matricula']}: {e}")
                   recalc_errors += 1
        else:
            try:
                target_matricula = target_matricula_str.split(" - ")[0]
                self.append_log(f"Recalculando saldo para {target_matricula_str}...")
                self.db.recalculate_full_balance_for_employee(target_matricula)
            except IndexError:
                self.append_log("ERRO: Nenhum funcionário selecionado para recalcular.")
                recalc_errors += 1
            except Exception as e:
                self.append_log(f"ERRO ao recalcular saldo para {target_matricula}: {e}")
                recalc_errors += 1

        if recalc_errors == 0:
            self.append_log("Recálculo concluído com sucesso.")
            messagebox.showinfo("Concluído", "Saldos recalculados e panorama atualizado.")
        else:
             self.append_log(f"Recálculo concluído com {recalc_errors} erro(s).")
             messagebox.showwarning("Atenção", f"Recálculo concluído com {recalc_errors} erro(s). Verifique o log.")

        # Agora, atualiza a visualização
        self.load_point_viewer(force_reload=True)
        self._update_calendar_tags()


    def setup_point_viewer(self, parent_frame):
        frame_viewer = ttk.LabelFrame(parent_frame, text=" Panorama ", style='TLabelframe')
        frame_viewer.grid(row=1, column=0, sticky="nsew", pady=5, padx=(0, 5))

        frame_viewer.grid_rowconfigure(3, weight=5)
        frame_viewer.grid_columnconfigure(0, weight=1)

        frame_controls = tk.Frame(frame_viewer, bg="#0a192f");
        frame_controls.grid(row=0, column=0, sticky="ew", pady=(5,0), padx=10)
        tk.Label(frame_controls, text="Funcionário:", bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(0,5))
        self.cmb_filter_func = ttk.Combobox(frame_controls, state="readonly", width=40)
        self.cmb_filter_func.pack(side=tk.LEFT, padx=(0, 20))
        self.cmb_filter_func.bind("<<ComboboxSelected>>", lambda e: self.load_point_viewer(force_reload=True))

        action_button_frame = tk.Frame(frame_controls, bg="#0a192f")
        action_button_frame.pack(side=tk.RIGHT)

        ttk.Button(action_button_frame, text="Recalcular e Atualizar", command=self.on_recalculate_and_refresh).pack(side=tk.LEFT, padx=5)

        ttk.Button(action_button_frame, text="📄 Exportar Ponto", command=self.on_export_panorama).pack(side=tk.LEFT, padx=5)

        ttk.Button(action_button_frame, text="💾 Salvar", command=self.commit_all_changes).pack(side=tk.LEFT, padx=5)

        calendar_frame = tk.Frame(frame_viewer, bg="#0a192f")
        calendar_frame.grid(row=1, column=0, sticky="ew", pady=5, padx=10)
        calendar_frame.grid_columnconfigure(1, weight=1)
        calendar_frame.grid_columnconfigure(2, weight=1)
        calendar_frame.grid_rowconfigure(1, weight=1)

        try:
            min_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        except:
            min_date = None

        self.main_calendar = Calendar(calendar_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR',
                                      background="#008080", foreground="white", headersbackground="#008080",
                                      normalbackground="#112240", weekendbackground="#172a45",
                                      othermonthbackground="#0a192f", othermonthforeground="#6a7b9d",
                                      selectbackground=self.ACCENT_COLOR,
                                      mindate=min_date)

        self.main_calendar.grid(row=0, column=0, rowspan=2, padx=(0, 20), sticky='n')
        self.main_calendar.bind("<<CalendarSelected>>", self.on_calendar_click)
        self.main_calendar.bind("<<CalendarMonthChanged>>", self.on_calendar_month_changed)

        self.main_calendar.tag_config('start_date', background=self.START_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('end_date', background=self.END_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('range_date', background=self.RANGE_BG_COLOR, foreground='#ccd6f6')
        self.main_calendar.tag_config('holiday', background=self.HOLIDAY_COLOR, foreground='white')

        period_frame = tk.Frame(calendar_frame, bg="#0a192f")
        period_frame.grid(row=0, column=1, columnspan=2, sticky='nw', padx=5)

        tk.Label(period_frame, text="Período:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        start_frame = tk.Frame(period_frame, bg="#0a192f")
        start_frame.pack(anchor='w', pady=2)
        tk.Label(start_frame, text="Início:", bg="#0a1f2f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_start = tk.Label(start_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_start.pack(side=tk.LEFT)

        end_frame = tk.Frame(period_frame, bg="#0a192f")
        end_frame.pack(anchor='w', pady=2)
        tk.Label(end_frame, text="Fim:", bg="#0a192f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_end = tk.Label(end_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_end.pack(side=tk.LEFT)

        holiday_frame = tk.Frame(calendar_frame, bg=self.BG_COLOR)
        holiday_frame.grid(row=1, column=1, sticky='nsew', padx=5, pady=(10,0))
        tk.Label(holiday_frame, text="Feriados:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 2))
        holiday_list_frame = tk.Frame(holiday_frame, bg=self.BG_COLOR)
        holiday_list_frame.pack(fill=tk.BOTH, expand=True)
        holiday_scrollbar = ttk.Scrollbar(holiday_list_frame, orient=tk.VERTICAL)
        self.holiday_listbox = tk.Listbox(holiday_list_frame, yscrollcommand=holiday_scrollbar.set, bg=self.LIGHT_BG, fg=self.FG_COLOR, selectbackground=self.ACCENT_COLOR, selectforeground=self.FG_COLOR, borderwidth=0, highlightthickness=0, activestyle='none', height=3)
        holiday_scrollbar.config(command=self.holiday_listbox.yview)
        holiday_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.holiday_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        punishment_frame = tk.Frame(calendar_frame, bg=self.BG_COLOR)
        punishment_frame.grid(row=1, column=2, sticky='nsew', padx=5, pady=(10,0))
        tk.Label(punishment_frame, text="Punições:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 2))
        punishment_list_frame = tk.Frame(punishment_frame, bg=self.BG_COLOR)
        punishment_list_frame.pack(fill=tk.BOTH, expand=True)
        punishment_scrollbar = ttk.Scrollbar(punishment_list_frame, orient=tk.VERTICAL)
        self.punishment_listbox = tk.Listbox(punishment_list_frame, yscrollcommand=punishment_scrollbar.set, bg=self.LIGHT_BG, fg=self.FG_COLOR, selectbackground=self.ACCENT_COLOR, selectforeground=self.FG_COLOR, borderwidth=0, highlightthickness=0, activestyle='none', height=3)
        punishment_scrollbar.config(command=self.punishment_listbox.yview)
        punishment_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.punishment_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lbl_total_punishments = tk.Label(punishment_frame, text="Total Punições: --", bg="#0a192f", fg=self.FG_COLOR, font=('Segoe UI', 9))
        self.lbl_total_punishments.pack(anchor='w', pady=(2, 0))

        frame_saldos = ttk.LabelFrame(frame_viewer, text=" Saldos Atuais", style='TLabelframe')
        frame_saldos.grid(row=2, column=0, sticky="ew", pady=(10, 5), padx=10)
        tk.Label(frame_saldos, text="BH:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(10,0)); self.lbl_saldo_bh_total = tk.Label(frame_saldos, text="--:--:--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_saldo_bh_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Extras:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_saldo_extras_total = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_saldo_extras_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Fichado:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_fichado_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_fichado_status.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Setor:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_setor_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_setor_status.pack(side=tk.LEFT, padx=5)

        tree_frame = tk.Frame(frame_viewer, bg="#0a192f");
        tree_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        columns = ("Matrícula", "Nome", "Data", "E1", "S1", "E2", "S2", "Carga_Horaria", "Punição", "Total_Desconto");
        self.tree_viewer = ttk.Treeview(tree_frame, columns=columns, show="headings")
        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_viewer.yview)
        h_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_viewer.xview)
        self.tree_viewer.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        self.tree_viewer.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        h_scroll.grid(row=1, column=0, sticky='ew')

        col_widths = {"Matrícula": 80, "Nome": 220, "Data": 80, "E1": 60, "S1": 60, "E2": 60, "S2": 60, "Carga_Horaria": 90, "Punição": 80, "Total_Desconto": 100}
        for col in columns:
            anchor = tk.W if col == "Nome" else tk.CENTER
            self.tree_viewer.heading(col, text=col.replace('_', ' ').replace('Carga Horaria', 'Carga Horária'))
            self.tree_viewer.column(col, width=col_widths.get(col, 100), anchor=anchor, stretch=tk.NO)

        self.tree_viewer.bind('<ButtonRelease-1>', self.start_in_place_edit)
        self.tree_viewer.tag_configure('evenrow', background='#112240')
        self.tree_viewer.tag_configure('oddrow', background='#172a45')
        self.tree_viewer.tag_configure('incomplete', foreground='#FF6B6B') # Vermelho


        self.update_employee_filter()
        self._update_calendar_tags()


    def on_calendar_month_changed(self, event=None): self._update_calendar_tags()
    def _clear_calendar_tags(self): self.main_calendar.calevent_remove('all')
    def _update_calendar_tags(self):
        self._clear_calendar_tags()

        try:
            current_cal_year = self.main_calendar._date.year
            current_cal_month = self.main_calendar._date.month
            holidays_in_month = self.db.get_holidays_for_month(current_cal_year, current_cal_month)
            for holiday_date in holidays_in_month:
                self.main_calendar.calevent_create(holiday_date, 'Feriado', tags='holiday')
        except Exception as e:
            print(f"Erro ao buscar feriados: {e}")

        if self.selected_start_date:
            self.main_calendar.calevent_create(self.selected_start_date, 'Início', tags='start_date')
            self.lbl_selected_start.config(text=self.selected_start_date.strftime("%d/%m/%Y"))
        else:
            self.lbl_selected_start.config(text="--/--/----")

        if self.selected_end_date:
            self.main_calendar.calevent_create(self.selected_end_date, 'Fim', tags='end_date')
            self.lbl_selected_end.config(text=self.selected_end_date.strftime("%d/%m/%Y"))

            if self.selected_start_date and self.selected_start_date < self.selected_end_date:
                current_date = self.selected_start_date + timedelta(days=1)
                while current_date < self.selected_end_date:
                    self.main_calendar.calevent_create(current_date, '', tags='range_date')
                    current_date += timedelta(days=1)
        else:
            self.lbl_selected_end.config(text="--/--/----")

    def on_calendar_click(self, event=None):
        try:
            clicked_date = self.main_calendar.selection_get()
        except tk.TclError:
            return

        if not clicked_date:
            return

        try:
            min_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
            if clicked_date < min_date:
                clicked_date = min_date
                self.main_calendar.selection_set(clicked_date)
        except:
            pass

        if self.selecting_start:
            self.selected_start_date = clicked_date
            self.selected_end_date = None
            self.selecting_start = False
            self.lbl_selected_end.config(text="Selecione...")
        else:
            self.selected_end_date = clicked_date
            self.selecting_start = True

            if self.selected_start_date and self.selected_end_date and self.selected_end_date < self.selected_start_date:
                self.selected_start_date, self.selected_end_date = self.selected_end_date, self.selected_start_date

            # Chama load_point_viewer apenas quando a data final é selecionada
            self.load_point_viewer(force_reload=True)

        self._update_calendar_tags()


    def update_employee_filter(self):
        funcionarios = self.db.get_all_funcionarios(); nomes = ["Todos"] + [f"{f['matricula']} - {f['nome']}" for f in funcionarios]; self.cmb_filter_func['values'] = nomes; self.cmb_filter_func.set("Todos")

    def load_point_viewer(self, force_reload=False):
        if self.unsaved_edits and not force_reload:
            if not messagebox.askyesno("Atualizar", "Alterações não salvas. Continuar?"): return
            self.unsaved_edits = {}
        if hasattr(self, 'holiday_listbox'): self.holiday_listbox.delete(0, tk.END)
        if hasattr(self, 'punishment_listbox'): self.punishment_listbox.delete(0, tk.END)
        if hasattr(self, 'lbl_total_punishments'): self.lbl_total_punishments.config(text="Total Punições: --")

        start_date = self.selected_start_date; end_date = self.selected_end_date

        if not start_date or not end_date:
            [self.tree_viewer.delete(i) for i in self.tree_viewer.get_children()]
            self.lbl_saldo_bh_total.config(text="--:--:--")
            self.lbl_saldo_extras_total.config(text="--")
            self.lbl_fichado_status.config(text="--")
            self.lbl_setor_status.config(text="--")
            for l in [getattr(self, 'holiday_listbox', None), getattr(self, 'punishment_listbox', None)]:
                if l: l.delete(0, tk.END)
            for lbl in [getattr(self, 'lbl_total_punishments', None)]:
                if lbl: lbl.config(text="Total Punições: --")
            return

        selected_func = self.cmb_filter_func.get(); target_matricula = selected_func.split(" - ")[0] if selected_func != "Todos" else None; [self.tree_viewer.delete(i) for i in self.tree_viewer.get_children()]

        try:
            panorama_data = self.db.get_point_panorama(start_date, end_date, target_matricula)
        except NameError as ne:
             error_msg = f"Erro ao gerar panorama (NameError): {ne}. Verifique a função 'get_expected_daily_minutes'."
             self.append_log(f"ERRO: {error_msg}")
             messagebox.showerror("Erro de Cálculo", error_msg)
             [self.tree_viewer.delete(i) for i in self.tree_viewer.get_children()]
             panorama_data = []
        except Exception as e:
             error_msg = f"Erro inesperado ao gerar panorama: {e}"
             self.append_log(f"ERRO: {error_msg}")
             messagebox.showerror("Erro Inesperado", error_msg)
             [self.tree_viewer.delete(i) for i in self.tree_viewer.get_children()]
             panorama_data = []


        last_item = None
        for i, item in enumerate(panorama_data):
            data_db_str = item['Data']; data_ptbr = datetime.strptime(data_db_str, "%Y-%m-%d").strftime("%d/%m/%Y") if data_db_str else data_db_str
            punicao_minutos = self.db.get_total_punishment_minutes_for_day(item['Matricula'], data_db_str); punicao_hms = format_minutes_to_hms(punicao_minutos) if punicao_minutos > 0 else "00:00:00"

            values = (item['Matricula'], item['Nome'], data_ptbr, item['E1'], item['S1'], item['E2'], item['S2'], item['Carga_Horaria'], punicao_hms, item['Total_Desconto'])
            
            tags_para_linha = []
            tags_para_linha.append('evenrow' if i % 2 == 0 else 'oddrow')
            if item.get('is_incomplete', False):
                tags_para_linha.append('incomplete')
            
            self.tree_viewer.insert("", "end", values=values, iid=(item['Matricula'], item['Data']), tags=tuple(tags_para_linha))
            
            last_item = item

        if target_matricula:
            func_info = self.db.get_funcionario_info(target_matricula)

            self.lbl_saldo_bh_total.config(text=format_minutes_to_hms(func_info.get('banco_horas', 0)))
            self.lbl_saldo_extras_total.config(text=str(int(func_info.get('extras_disponiveis', 0))))

            fichado_val = func_info.get('fichado', 0); fichado_str = "Sim" if fichado_val == 1 else "Não"; setor_str = func_info.get('setor', 'N/D'); self.lbl_fichado_status.config(text=fichado_str); self.lbl_setor_status.config(text=setor_str)
        else:
            self.lbl_saldo_bh_total.config(text="--:--:--"); self.lbl_saldo_extras_total.config(text="--"); self.lbl_fichado_status.config(text="--"); self.lbl_setor_status.config(text="--")

        if start_date and end_date and hasattr(self, 'holiday_listbox'):
            holidays = self.db.get_holidays_in_range(start_date, end_date); [self.holiday_listbox.insert(tk.END, f"{datetime.strptime(h['data'], '%Y-%m-%d').strftime('%d/%m/%Y')} - {h['descricao']} ({h['tipo']})") for h in holidays if h.get('data')]

        if target_matricula and start_date and end_date and hasattr(self, 'punishment_listbox'):
            punishments = self.db.get_punishments_in_range(target_matricula, start_date, end_date); total_punishments = len(punishments); self.lbl_total_punishments.config(text=f"Total Punições: {total_punishments}"); [self.punishment_listbox.insert(tk.END, f"{datetime.strptime(p['data_punicao'], '%Y-%m-%d').strftime('%d/%m/%Y')} - {format_minutes_to_hms(p['minutos_descontados'])} - {p.get('motivo','Sem motivo')}") for p in punishments if p.get('data_punicao')]
        elif hasattr(self, 'punishment_listbox'):
            self.punishment_listbox.delete(0, tk.END); self.lbl_total_punishments.config(text="Total Punições: --")

    def on_export_panorama(self):
        selected_func_str = self.cmb_filter_func.get()
        start_date = self.selected_start_date
        end_date = self.selected_end_date

        if not start_date or not end_date:
            messagebox.showerror("Erro", "Selecione um período válido (Data Início e Fim).")
            return

        if not selected_func_str:
            messagebox.showerror("Erro", "Selecione um funcionário.")
            return

        data_rows = self.tree_viewer.get_children("")
        if not data_rows:
            messagebox.showinfo("Aviso", "Não há dados para exportar na visão atual.")
            return

        target_matricula = selected_func_str.split(" - ")[0] if selected_func_str != "Todos" else "Todos"
        nome_func = " ".join(selected_func_str.split(" - ")[1:]) if selected_func_str != "Todos" else "Todos_Funcionarios"

        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            title="Salvar Espelho de Ponto",
            initialfile=f"Espelho_Ponto_{nome_func.replace(' ','_')}_{start_date.isoformat()}_a_{end_date.isoformat()}.pdf"
        )
        if not filepath:
            return

        try:
            doc = SimpleDocTemplate(filepath, pagesize=landscape(A4), rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
            styles = getSampleStyleSheet()
            story = []

            style_title = styles['h1']
            style_title.alignment = TA_CENTER
            style_title.textColor = colors.teal

            style_header = styles['h2']
            style_header.fontSize = 10
            style_header.alignment = TA_LEFT

            style_body = styles['Normal']
            style_body.fontSize = 8

            style_table_header = styles['Normal']
            style_table_header.fontSize = 8
            style_table_header.fontName = 'Helvetica-Bold'
            style_table_header.alignment = TA_CENTER

            style_table_body = styles['Normal']
            style_table_body.fontSize = 7
            style_table_body.alignment = TA_CENTER
            
            style_table_body_incomplete = styles['Normal']
            style_table_body_incomplete.fontSize = 7
            style_table_body_incomplete.alignment = TA_CENTER
            style_table_body_incomplete.textColor = colors.red


            style_nome = TableStyle([('ALIGN', (0,0), (0,0), 'LEFT'),
                                     ('ALIGN', (1,0), (1,0), 'RIGHT')])

            if LOGO_PATH.exists():
                story.append(Image(LOGO_PATH, width=3*cm, height=3*cm, hAlign='CENTER'))
                story.append(Spacer(1, 0.2*cm))

            story.append(Paragraph("Espelho de Ponto", style_title))
            story.append(Spacer(1, 1*cm))

            story.append(Paragraph(f"<b>Período:</b> {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}", styles['Normal']))

            if target_matricula != "Todos":
                story.append(Paragraph(f"<b>Funcionário:</b> {nome_func} (Mat. {target_matricula})", styles['Normal']))
                story.append(Spacer(1, 0.5*cm))

                last_bh_saldo = self.lbl_saldo_bh_total.cget('text')
                last_extras = self.lbl_saldo_extras_total.cget('text')

                saldo_data = [
                    [Paragraph(f"<b>BH Saldo Final ({end_date.strftime('%d/%m')}):</b> {last_bh_saldo}", style_header),
                     Paragraph(f"<b>Extras ({end_date.strftime('%d/%m')}):</b> {last_extras}", style_header),
                     Paragraph(f"<b>Fichado:</b> {self.lbl_fichado_status.cget('text')}", style_header),
                     Paragraph(f"<b>Setor:</b> {self.lbl_setor_status.cget('text')}", style_header)]
                ]
                saldo_table = Table(saldo_data, colWidths=[6*cm, 6*cm, 6*cm, 8*cm])
                saldo_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
                story.append(saldo_table)

            story.append(Spacer(1, 1*cm))

            col_headers = ["Mat.", "Nome", "Data", "E1", "S1", "E2", "S2", "Carga", "Punição", "Desconto"]
            table_data = [[Paragraph(h, style_table_header) for h in col_headers]]

            col_widths = [1.8*cm, 5.5*cm, 2.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm, 2.5*cm, 2.5*cm, 2.5*cm]

            for item_id in data_rows:
                values = self.tree_viewer.item(item_id, 'values')
                tags = self.tree_viewer.item(item_id, 'tags')
                
                cell_style = style_table_body_incomplete if 'incomplete' in tags else style_table_body

                row_data = [
                    Paragraph(values[0], cell_style),
                    Paragraph(values[1], cell_style),
                    Paragraph(values[2], cell_style),
                    Paragraph(values[3], cell_style),
                    Paragraph(values[4], cell_style),
                    Paragraph(values[5], cell_style),
                    Paragraph(values[6], cell_style),
                    Paragraph(values[7], cell_style),
                    Paragraph(values[8], cell_style),
                    Paragraph(values[9], cell_style),
                ]
                table_data.append(row_data)

            t = Table(table_data, colWidths=col_widths)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.teal),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('BOX', (0,0), (-1,-1), 1, colors.black),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN', (0,1), (0,-1), 'LEFT'),
                ('ALIGN', (1,1), (1,-1), 'LEFT'),
            ]))
            story.append(t)

            if target_matricula != "Todos":
                story.append(Spacer(1, 2.5*cm))
                story.append(Paragraph("________________________________________", styles['Normal']))
                story.append(Paragraph(nome_func, styles['Normal']))
                story.append(Paragraph(f"Data: ____/____/{datetime.now().year}", styles['Normal']))

            doc.build(story)
            messagebox.showinfo("Sucesso", f"Espelho de Ponto salvo:\n{filepath}")

        except PermissionError:
             messagebox.showerror("Erro", f"Erro de Permissão.\nO arquivo '{filepath}' pode estar aberto. Feche-o e tente novamente.")
        except Exception as e:
            messagebox.showerror("Erro PDF", f"Não foi possível gerar o PDF: {e}")
            self.append_log(f"ERRO PDF: {e}")

    def append_log(self, text):
        if hasattr(self, 'log_area'):
            self.log_area.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {text}\n");
            self.log_area.see(tk.END)
        else:
            print(text)

    def start_in_place_edit(self, event):
        if self.editing_widgets: [w.destroy() for w in self.editing_widgets.values()]; self.editing_widgets.clear()
        item_id = self.tree_viewer.identify_row(event.y);
        if not item_id: return
        column_id = self.tree_viewer.identify_column(event.x)
        try: col_index = int(column_id.replace('#', '')) - 1 ; column_name = self.tree_viewer.heading(column_id, 'text')
        except: self.append_log(f"Erro edição: coluna."); return
        editable_columns = ["E1", "S1", "E2", "S2"];
        if column_name not in editable_columns: return
        x, y, width, height = self.tree_viewer.bbox(item_id, column_id); values = self.tree_viewer.item(item_id, 'values'); matricula, data_ptbr, current_time = values[0], values[2], values[col_index]
        data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d");

        if data_db < SYSTEM_START_DATE:
            self.append_log(f"Edição bloqueada. Data {data_db} é anterior ao início do sistema ({SYSTEM_START_DATE}).")
            return

        entry_edit = ttk.Entry(self.tree_viewer); entry_edit.place(x=x, y=y, width=width, height=height)
        entry_edit.insert(0, current_time if current_time not in ('', 'N/A') else ''); entry_edit.focus(); justificativa_cmb = ttk.Combobox(self.tree_viewer, values=LISTA_JUSTIFICATIVAS, state="readonly", width=30); justificativa_cmb.place(x=x + width + 5, y=y, height=height)
        edit_key = (matricula, data_db); justificativa_cmb.set(self.unsaved_edits.get(edit_key, {}).get('justificativa', LISTA_JUSTIFICATIVAS[0])); self.editing_widgets = {'entry': entry_edit, 'cmb': justificativa_cmb}
        def on_escape(e=None):
             if self.editing_widgets: [w.destroy() for w in self.editing_widgets.values()]; self.editing_widgets.clear()
        def handle_edit(from_cmb=False):
            if not self.editing_widgets: return
            entry = self.editing_widgets.get('entry'); cmb = self.editing_widgets.get('cmb');
            if not entry or not cmb: return
            new_time, just = entry.get().strip(), cmb.get()
            if not (re.match(r'^\d{2}:\d{2}$', new_time) or new_time in ('', 'N/A', '00:00')):
                if new_time != current_time: messagebox.showerror("Erro Formato", "Formato de hora inválido. Use HH:MM.", parent=self.root); on_escape(); return
            temp_vals = list(self.tree_viewer.item(item_id, 'values')); temp_vals[col_index] = new_time; self.tree_viewer.item(item_id, values=tuple(temp_vals))
            if edit_key not in self.unsaved_edits: current_row_values = self.tree_viewer.item(item_id, 'values'); self.unsaved_edits[edit_key] = {'E1': current_row_values[3], 'S1': current_row_values[4], 'E2': current_row_values[5], 'S2': current_row_values[6]}
            self.unsaved_edits[edit_key][column_name] = new_time; self.unsaved_edits[edit_key]['justificativa'] = just; self.update_visual_work_hours(item_id)
            if from_cmb: on_escape()
        entry_edit.bind('<Return>', lambda e: handle_edit(from_cmb=True)); entry_edit.bind('<Escape>', on_escape); entry_edit.bind('<FocusOut>', lambda e: on_escape()); justificativa_cmb.bind('<<ComboboxSelected>>', lambda e: handle_edit(from_cmb=True)); justificativa_cmb.bind('<Escape>', on_escape)

    def update_visual_work_hours(self, item_id):
        values = self.tree_viewer.item(item_id, 'values'); matricula = values[0]; data_ptbr = values[2]; data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        all_times_raw = [values[3], values[4], values[5], values[6]]; func_info = self.db.get_funcionario_info(matricula); sector = func_info.get('setor', 'N/D'); minutos_totais_liquidos = 0
        penalidade_total_dia = 0
        periodos_calculados = []
        is_incomplete = False # Flag para batida ímpar

        for i in range(0, 4, 2):
            e_time, s_time = all_times_raw[i], all_times_raw[i+1]
            if e_time and s_time and e_time not in ('N/A', '00:00', '') and s_time not in ('N/A', '00:00', ''):
                try:
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M");
                    saida = datetime.strptime(f"{data_db} {s_time}", "%Y-%m-%d %H:%M")
                    if saida < entrada: saida += timedelta(days=1)

                    turno = "Manhã" if i == 0 else "Tarde"
                    jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")

                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                    deduction_min_periodo = calculate_deduction(late_min, sector)
                    penalidade_total_dia += deduction_min_periodo

                    inicio_efetivo = jornada_inicio + timedelta(minutes=deduction_min_periodo)
                    inicio_real_contagem = max(entrada, inicio_efetivo)
                    liquido_min_periodo = 0
                    if saida > inicio_real_contagem:
                        liquido_min_periodo = (saida - inicio_real_contagem).total_seconds() / 60

                    minutos_totais_liquidos += liquido_min_periodo

                    periodos_calculados.append({
                        "entrada": str(entrada), "saida": str(saida),
                        "minutos_brutos": format_minutes_to_hms((saida - entrada).total_seconds() / 60),
                        "deducao_minutos": format_minutes_to_hms(deduction_min_periodo),
                        "minutos_liquidos": format_minutes_to_hms(liquido_min_periodo)
                    })
                except ValueError:
                    continue
            elif e_time and not s_time and e_time not in ('N/A', '00:00', ''):
                try:
                    is_incomplete = True # Marca como incompleto
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M");
                    
                    turno = "Manhã" if i == 0 else "Tarde"
                    jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")

                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                    deduction_min_periodo = calculate_deduction(late_min, sector)
                    penalidade_total_dia += deduction_min_periodo
                    
                    minutos_totais_liquidos += 0 
                    
                    periodos_calculados.append({
                        "entrada": str(entrada), "saida": None,
                        "minutos_brutos": "00:00:00",
                        "deducao_minutos": format_minutes_to_hms(deduction_min_periodo),
                        "minutos_liquidos": "00:00:00"
                    })
                except ValueError:
                    continue

        new_values = list(values);
        new_values[7] = format_minutes_to_hms(minutos_totais_liquidos)
        new_values[9] = format_minutes_to_hms(penalidade_total_dia)
        
        # Atualiza as tags da linha (remove/adiciona 'incomplete')
        current_tags = list(self.tree_viewer.item(item_id, 'tags'))
        if is_incomplete and 'incomplete' not in current_tags:
            current_tags.append('incomplete')
        elif not is_incomplete and 'incomplete' in current_tags:
            current_tags.remove('incomplete')
            
        self.tree_viewer.item(item_id, values=tuple(new_values), tags=tuple(current_tags))


        edit_key = (matricula, data_db)
        if edit_key in self.unsaved_edits:
            # Atualiza os períodos recalculados para serem salvos corretamente
            self.unsaved_edits[edit_key]['periodos_recalculados'] = periodos_calculados


    def process_manual_update_and_save(self, matricula, data_db, all_times_raw, justificativa):
        func_info = self.db.get_funcionario_info(matricula); sector = func_info.get('setor', 'N/D'); periodos, minutos_totais = [], 0
        for i in range(0, 4, 2):
            e_time, s_time = all_times_raw[i], all_times_raw[i+1]
            
            # Caso 1: Período completo
            if e_time and s_time and e_time not in ('N/A', '00:00', '') and s_time not in ('N/A', '00:00', ''):
                try:
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M");
                    saida = datetime.strptime(f"{data_db} {s_time}", "%Y-%m-%d %H:%M")
                    if saida < entrada: saida += timedelta(days=1)

                    turno = "Manhã" if i == 0 else "Tarde"
                    jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")

                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                    deduction_min = calculate_deduction(late_min, sector)

                    inicio_efetivo = jornada_inicio + timedelta(minutes=deduction_min)
                    inicio_real_contagem = max(entrada, inicio_efetivo)
                    liquido_min = 0
                    if saida > inicio_real_contagem:
                        liquido_min = (saida - inicio_real_contagem).total_seconds() / 60

                    minutos_totais += liquido_min
                    periodos.append({
                        "entrada": str(entrada), "saida": str(saida),
                        "minutos_brutos": format_minutes_to_hms((saida - entrada).total_seconds() / 60),
                        "deducao_minutos": format_minutes_to_hms(deduction_min),
                        "minutos_liquidos": format_minutes_to_hms(liquido_min)
                    })
                except ValueError:
                    self.append_log(f"ERRO ao salvar formato de hora '{e_time}' ou '{s_time}' para {matricula} em {data_db}."); continue
            
            # Caso 2: Apenas Entrada
            elif e_time and not s_time and e_time not in ('N/A', '00:00', ''):
                try:
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M");
                    
                    turno = "Manhã" if i == 0 else "Tarde"
                    jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")

                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                    deduction_min = calculate_deduction(late_min, sector)

                    minutos_totais += 0
                    periodos.append({
                        "entrada": str(entrada), "saida": None,
                        "minutos_brutos": "00:00:00",
                        "deducao_minutos": format_minutes_to_hms(deduction_min),
                        "minutos_liquidos": "00:00:00"
                    })
                except ValueError:
                    self.append_log(f"ERRO ao salvar formato de hora '{e_time}' para {matricula} em {data_db}."); continue

        self.db.insert_horas_trabalhadas({
            "matricula": matricula,
            "data": data_db,
            "minutos_totais": format_minutes_to_hms(minutos_totais),
            "periodos": periodos
        }, justificativa=justificativa)
        self.append_log(f"Ponto {matricula} {data_db} atualizado. Just: '{justificativa}'.")


    def commit_all_changes(self, from_exit=False):
        if self.editing_widgets: [w.event_generate('<FocusOut>') for k, w in self.editing_widgets.items() if k == 'entry']
        if not self.unsaved_edits:
            if not from_exit:
                messagebox.showinfo("Salvar", "Nenhuma alteração.")
            return

        if not from_exit:
            if not messagebox.askyesno("Confirmar", f"{len(self.unsaved_edits)} dia(s) alterados. Salvar e recalcular?"):
                return

        self.append_log(f"Salvando {len(self.unsaved_edits)} alterações..."); affected_employees = set()
        for (matricula, data_db), edits in self.unsaved_edits.items():
            affected_employees.add(matricula);
            justificativa = edits.get('justificativa', 'Ajuste Manual');
            self.process_manual_update_and_save(matricula, data_db, [edits.get('E1',''), edits.get('S1',''), edits.get('E2',''), edits.get('S2','')], justificativa)

        self.append_log("Recalculando saldos...");
        recalc_errors = 0
        for mat in affected_employees:
             try:
                self.db.recalculate_full_balance_for_employee(mat)
             except Exception as e:
                self.append_log(f"ERRO ao recalcular saldo para {mat} após salvar edições: {e}")
                recalc_errors += 1

        self.unsaved_edits = {}

        if not from_exit:
            if recalc_errors == 0:
                messagebox.showinfo("Sucesso", "Alterações salvas e saldos recalculados.")
            else:
                messagebox.showwarning("Atenção", f"Alterações salvas, mas ocorreram {recalc_errors} erro(s) durante o recálculo.\nVerifique o log.")
            self.load_point_viewer(force_reload=True); self._update_calendar_tags()


# --- Ponto de Entrada Principal ---
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()