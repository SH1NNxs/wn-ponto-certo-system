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
import threading
import requests
import webbrowser
from packaging import version
import subprocess
import tempfile

# --- VERSÃO ATUAL ---
CURRENT_VERSION = "v1.3.0"

# Define a data atual para referência dos cálculos de saldo
SYSTEM_CURRENT_DATE = date.today()

# Inicializa o Marco Zero do sistema (será atualizado pelo banco de dados)
SYSTEM_START_DATE = "2025-01-01"

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
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
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

def create_database(self):
        c = self.conn.cursor()
        # ... (suas criações de tabelas permanecem iguais)
        
        self.conn.commit()

def create_database(self):
        global SYSTEM_START_DATE 
        c = self.conn.cursor()
        
        # Criação de todas as tabelas (Funcionarios, configuracoes, horas_trabalhadas, etc.)
        # ... (mantenha seus comandos c.execute atuais aqui) ...

        self.conn.commit()

        # Busca a configuração gravada no SSD
        c.execute("SELECT valor FROM configuracoes WHERE chave = 'data_inicio_sistema'")
        config_data = c.fetchone()

        if not config_data:
            from tkinter import simpledialog, messagebox
            data_digitada = simpledialog.askstring("Configuração Inicial", "Data de início dos cálculos (DD/MM/AAAA):")
            if data_digitada:
                try:
                    data_iso = datetime.strptime(data_digitada, "%d/%m/%Y").strftime("%Y-%m-%d")
                    c.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", ('data_inicio_sistema', data_iso))
                    self.conn.commit()
                    SYSTEM_START_DATE = data_iso
                except:
                    SYSTEM_START_DATE = "2025-01-01"
            else:
                SYSTEM_START_DATE = "2025-01-01"
        else:
            # ESSENCIAL: Atualiza a variável global com o que está no banco
            SYSTEM_START_DATE = config_data['valor']

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

# --- FUNÇÃO calculate_deduction ---
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
            # (Primeiros 15 min * 3) + (Minutos 16 a 30 * 2) -> Total 75 min para 30 min de atraso
            penalty_first_15 = 15 * 3 # 45 minutos
            penalty_next_minutes = (minutes_late - 15) * 2 # Ex: (30-15)*2 = 15*2 = 30 min
            return penalty_first_15 + penalty_next_minutes # Total = 45 + 30 = 75 min
        else: # minutes_late > 30
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

def calculate_period_data(entrada, saida, data_ref, turno_idx, sector, ignore_delay_flag=False):
    """
    Calcula minutos brutos, líquidos e dedução.
    Corrige contagem de horas antecipadas (Caso Iggor) e permite ignorar atrasos.
    """
    if not entrada: return 0, 0, 0
        
    # Define horário oficial (07:30 Manhã / 13:00 Tarde)
    horario_inicio_str = '07:30' if turno_idx < 2 else '13:00'
    jornada_inicio = datetime.strptime(f"{data_ref} {horario_inicio_str}", "%Y-%m-%d %H:%M")

    # Calcula diferença (negativo = chegou cedo, positivo = atrasado)
    minutes_diff = (entrada - jornada_inicio).total_seconds() / 60
    
    deduction_minutes = 0
    
    # Lógica de Atraso
    if minutes_diff > 0:
        if not ignore_delay_flag:
            deduction_minutes = calculate_deduction(minutes_diff, sector)
        
        # Se atrasou, o início conta a partir da punição (ou da entrada se punição for menor)
        inicio_com_punicao = jornada_inicio + timedelta(minutes=deduction_minutes)
        inicio_contabilizavel = max(entrada, inicio_com_punicao)
    else:
        # CORREÇÃO: Se chegou CEDO ou na hora, conta a partir da entrada física.
        inicio_contabilizavel = entrada

    if not saida: return 0, 0, deduction_minutes

    duration_bruto = (saida - entrada).total_seconds() / 60
    duration_liquido = 0
    
    if saida > inicio_contabilizavel:
        duration_liquido = (saida - inicio_contabilizavel).total_seconds() / 60
    
    return duration_bruto, duration_liquido, deduction_minutes

# --- Classe DatabaseManager ---
# --- Classe DatabaseManager ---
class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = str(db_path if db_path else DEFAULT_DB)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_database()
        self.check_migrations() 
        self.populate_fixed_holidays()

    def check_migrations(self):
        c = self.conn.cursor()
        # Verifica ignorar_atraso
        try:
            c.execute("SELECT ignorar_atraso FROM horas_trabalhadas LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE horas_trabalhadas ADD COLUMN ignorar_atraso INTEGER DEFAULT 0")
        
        # GARANTIA: Verifica se a matricula está na tabela de logs (comum dar erro aqui)
        try:
            c.execute("SELECT matricula FROM log_edicoes LIMIT 1")
        except sqlite3.OperationalError:
            # Se não existir na log_edicoes, o erro "no such column" aparece ao gerar panorama
            c.execute("ALTER TABLE log_edicoes ADD COLUMN matricula TEXT")
            
        self.conn.commit()

    def toggle_ignore_delay(self, matricula, data_str):
        """Alterna o status de ignorar atraso e recalcula o dia."""
        c = self.conn.cursor()
        c.execute("SELECT ignorar_atraso, periodos FROM horas_trabalhadas WHERE matricula=? AND data=?", (matricula, data_str))
        row = c.fetchone()
        if not row: return False
        
        novo_status = 1 if row['ignorar_atraso'] == 0 else 0
        periodos = json.loads(row['periodos'])
        minutos_totais_novo = 0
        novos_periodos = []
        func_info = self.get_funcionario_info(matricula)
        setor = func_info.get('setor', 'N/D')
        
        for i, p in enumerate(periodos):
            if p.get('entrada') and p.get('saida'):
                 ent = datetime.strptime(p['entrada'], "%Y-%m-%d %H:%M:%S")
                 sai = datetime.strptime(p['saida'], "%Y-%m-%d %H:%M:%S")
                 # Recalcula usando a nova função
                 _, liquido, deducao = calculate_period_data(ent, sai, data_str, i*2, setor, ignore_delay_flag=(novo_status==1))
                 minutos_totais_novo += liquido
                 p['minutos_liquidos'] = format_minutes_to_hms(liquido)
                 p['deducao_minutos'] = format_minutes_to_hms(deducao)
            novos_periodos.append(p)
            
        with self.conn:
            self.conn.execute("UPDATE horas_trabalhadas SET ignorar_atraso=?, minutos_totais=?, periodos=? WHERE matricula=? AND data=?", 
                              (novo_status, format_minutes_to_hms(minutos_totais_novo), json.dumps(novos_periodos), matricula, data_str))
            self.log_edicao(matricula, data_str, f"Ignorar: {row['ignorar_atraso']}", f"Ignorar: {novo_status}", "Alteração Manual Atraso")
        return True

    def create_database(self):
        """
        Cria a estrutura de tabelas do banco de dados e verifica a configuração inicial.
        """
        c = self.conn.cursor()
        
        # Tabela de Funcionários
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

        # Tabela de Configurações (Marco Zero do Sistema)
        c.execute('''
            CREATE TABLE IF NOT EXISTS configuracoes (
                chave TEXT PRIMARY KEY,
                valor TEXT
            )
        ''')

        # Tabela de Horas Trabalhadas
        c.execute("""
            CREATE TABLE IF NOT EXISTS horas_trabalhadas (
                id INTEGER PRIMARY KEY, 
                matricula TEXT, 
                data TEXT, 
                minutos_totais TEXT, 
                periodos TEXT, 
                ignorar_atraso INTEGER DEFAULT 0, 
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP, 
                UNIQUE(matricula, data)
            )
        """)

        # Tabela de Logs de Edição
        c.execute("""
            CREATE TABLE IF NOT EXISTS log_edicoes (
                id INTEGER PRIMARY KEY, 
                matricula TEXT, 
                data_ponto TEXT, 
                data_edicao DATETIME DEFAULT CURRENT_TIMESTAMP, 
                periodos_antigos TEXT, 
                periodos_novos TEXT, 
                justificativa TEXT, 
                usuario TEXT DEFAULT 'SYSTEM/MANUAL'
            )
        """)

        # Tabelas de Feriados
        c.execute("CREATE TABLE IF NOT EXISTS feriados (id INTEGER PRIMARY KEY, data TEXT UNIQUE, descricao TEXT, tipo TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS feriados_recorrentes (id INTEGER PRIMARY KEY, dia INTEGER, mes INTEGER, descricao TEXT, tipo TEXT, UNIQUE(dia, mes))")

        # Tabelas de Punições e Abonos
        c.execute("""
            CREATE TABLE IF NOT EXISTS punicoes (
                id INTEGER PRIMARY KEY, 
                matricula TEXT, 
                data_punicao TEXT, 
                minutos_descontados REAL DEFAULT 0, 
                motivo TEXT, 
                data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, 
                FOREIGN KEY (matricula) REFERENCES funcionarios (matricula)
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS abonos (
                id INTEGER PRIMARY KEY, 
                matricula TEXT, 
                data TEXT, 
                motivo TEXT, 
                minutos_abonados REAL DEFAULT 0, 
                data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, 
                UNIQUE(matricula, data)
            )
        """)

        self.conn.commit()

        # --- LÓGICA DE MARCO ZERO (DATA DE INÍCIO) ---
        c.execute("SELECT valor FROM configuracoes WHERE chave = 'data_inicio_sistema'")
        config_data = c.fetchone()

        if not config_data:
            from tkinter import simpledialog, messagebox
            # Pergunta ao usuário a data de início para evitar saldos negativos retroativos
            data_inicio = simpledialog.askstring(
                "Configuração Inicial", 
                "O banco de dados é novo.\nInforme a data de início dos cálculos (DD/MM/AAAA):"
            )
            
            if data_inicio:
                # Salva a data para consultas futuras em cálculos de saldo
                c.execute("INSERT INTO configuracoes (chave, valor) VALUES (?, ?)", ('data_inicio_sistema', data_inicio))
                self.conn.commit()
                messagebox.showinfo("Sucesso", f"Marco zero definido para: {data_inicio}")
            else:
                messagebox.showwarning("Atenção", "Nenhuma data definida. Cálculos retroativos podem gerar saldos inesperados.")



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

    def add_holiday(self, data_str, descricao, tipo):
        try:
            self.conn.execute("INSERT OR REPLACE INTO feriados (data, descricao, tipo) VALUES (?, ?, ?)", (data_str, descricao, tipo))
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


    def get_total_punishment_minutes_for_day(self, matricula, data_str):
        c = self.conn.cursor()
        query = "SELECT SUM(minutos_descontados) as total FROM punicoes WHERE matricula = ? AND data_punicao = ?"
        c.execute(query, (matricula, data_str))
        result = c.fetchone()
        return result['total'] if result and result['total'] is not None else 0

    def get_punishments_in_range(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date
        query = "SELECT id, data_punicao, minutos_descontados, motivo FROM punicoes WHERE matricula = ? AND data_punicao BETWEEN ? AND ? AND data_punicao >= ? ORDER BY data_punicao"
        c.execute(query, (matricula, start_date_str, end_date_str, SYSTEM_START_DATE))
        return [dict(row) for row in c.fetchall()]
        
    def delete_punicao(self, punicao_id):
        try:
            with self.conn:
                c = self.conn.cursor()
                # 1. Pega os dados ANTES de deletar (para o log)
                c.execute("SELECT matricula, data_punicao, minutos_descontados, motivo FROM punicoes WHERE id = ?", (punicao_id,))
                row = c.fetchone()
                
                if row:
                    # 2. Deleta a punição
                    self.conn.execute("DELETE FROM punicoes WHERE id = ?", (punicao_id,))
                    
                    # 3. Loga a remoção (para o Power BI)
                    minutos_str = format_minutes_to_hms(row['minutos_descontados'] or 0)
                    log_antigo = f"Punição: {minutos_str} ({row['motivo'] or 'N/D'})"
                    log_novo = "Punição: Removida"
                    self.log_edicao(row['matricula'], row['data_punicao'], log_antigo, log_novo, "Remoção de Punição")
                    
                    return row['matricula'] # Retorna a matrícula para recalcular
            return False
        except Exception as e:
            print(f"Erro delete punição: {e}")
            return False
    
    def get_extras_paid_in_range(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date

        query = """
            SELECT periodos_antigos, periodos_novos
            FROM log_edicoes
            WHERE matricula = ?
              AND data_ponto BETWEEN ? AND ?
              AND justificativa = 'Pagamento/Dedução Saldo'
        """
        c.execute(query, (matricula, start_date_str, end_date_str))
        logs_pagamento = c.fetchall()

        total_extras_pagos = 0
        for log in logs_pagamento:
            try:
                antigo_str = log['periodos_antigos']
                novo_str = log['periodos_novos']

                extras_antigo_match = re.search(r'Extras: (\-?\d+)', antigo_str)
                extras_novo_match = re.search(r'Extras: (\-?\d+)', novo_str)

                if extras_antigo_match and extras_novo_match:
                    extras_antigo = int(extras_antigo_match.group(1))
                    extras_novo = int(extras_novo_match.group(1))
                    total_extras_pagos += (extras_antigo - extras_novo)
            except Exception as e:
                print(f"Erro ao parsear log de pagamento para get_extras_paid_in_range: {e}")

        return total_extras_pagos

    def get_payment_logs(self, matricula, start_date, end_date):
        """Busca apenas logs de 'Pagamento/Dedução Saldo' para a tela de estorno."""
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date

        query = """
            SELECT id, data_ponto, periodos_antigos, periodos_novos
            FROM log_edicoes
            WHERE matricula = ?
              AND data_ponto BETWEEN ? AND ?
              AND justificativa = 'Pagamento/Dedução Saldo'
            ORDER BY data_ponto DESC, id DESC
        """
        c.execute(query, (matricula, start_date_str, end_date_str))
        return [dict(row) for row in c.fetchall()]

    def reverse_payment(self, log_id):
        """Reverte um lançamento de pagamento (Estorno)."""
        try:
            with self.conn:
                c = self.conn.cursor()
                
                # 1. Pega o log original do pagamento
                c.execute("SELECT * FROM log_edicoes WHERE id = ? AND justificativa = 'Pagamento/Dedução Saldo'", (log_id,))
                log_row = c.fetchone()

                if not log_row:
                    # Verifica se já foi estornado
                    c.execute("SELECT 1 FROM log_edicoes WHERE id = ? AND justificativa LIKE '[ESTORNADO]%'", (log_id,))
                    if c.fetchone():
                        return False, "Este pagamento já foi estornado."
                    return False, "Log de pagamento não encontrado."
                
                matricula = log_row['matricula']
                antigo_str = log_row['periodos_antigos']
                novo_str = log_row['periodos_novos']

                # 2. Calcula o que foi pago
                extras_a_reverter = 0
                bh_a_reverter = 0

                try:
                    extras_antigo = int(re.search(r'Extras: (\-?\d+)', antigo_str).group(1))
                    extras_novo = int(re.search(r'Extras: (\-?\d+)', novo_str).group(1))
                    extras_a_reverter = extras_antigo - extras_novo
                except Exception:
                    pass # Ignora se não houver log de extras

                try:
                    bh_antigo = parse_hhmm_to_minutes(re.search(r'BH: ([\-\d:]+)', antigo_str).group(1))
                    bh_novo = parse_hhmm_to_minutes(re.search(r'BH: ([\-\d:]+)', novo_str).group(1))
                    bh_a_reverter = bh_antigo - bh_novo
                except Exception:
                    pass # Ignora se não houver log de BH

                if extras_a_reverter == 0 and bh_a_reverter == 0:
                    return False, "Nenhum valor a reverter neste log (ambos são zero)."

                # 3. Pega os saldos atuais
                func_info = self.get_funcionario_info(matricula)
                bh_atual = func_info.get('banco_horas', 0)
                extras_atual = func_info.get('extras_disponiveis', 0)
                
                # 4. Soma os valores de volta
                novo_bh = bh_atual + bh_a_reverter
                novo_extras = extras_atual + extras_a_reverter

                # 5. Atualiza o saldo do funcionário
                self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?",
                                  (novo_bh, novo_extras, matricula))
                
                # 6. Loga o Estorno (para Power BI)
                log_antigo_reverso = f"BH: {format_minutes_to_hms(bh_atual)}, Extras: {int(extras_atual)}"
                log_novo_reverso = f"BH: {format_minutes_to_hms(novo_bh)}, Extras: {int(novo_extras)}"
                self.log_edicao(matricula, date.today().isoformat(), log_antigo_reverso, log_novo_reverso, f"Estorno Pagamento (Ref. Log ID: {log_id})")

                # 7. --- NOVA ETAPA: Atualiza o log original para marcá-lo como estornado ---
                self.conn.execute("UPDATE log_edicoes SET justificativa = ? WHERE id = ?", 
                                  (f"[ESTORNADO] Pagamento/Dedução Saldo", log_id))

            return True, matricula # Sucesso
        
        except Exception as e:
            print(f"Erro em reverse_payment: {e}")
            return False, str(e)
    
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
                    minutos_str = format_minutes_to_hms(row['minutos_abonados'] or 0)
                    self.conn.execute("DELETE FROM abonos WHERE id = ?", (abono_id,))
                    self.log_edicao(row['matricula'], row['data'], f"Abono: {minutos_str} ({row['motivo'] or 'N/D'})", "Abono: Removido", "Remoção de Abono")
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

    def get_abono_minutes_for_day(self, matricula, data_str):
        c = self.conn.cursor()
        query = "SELECT minutos_abonados FROM abonos WHERE matricula = ? AND data = ?"
        c.execute(query, (matricula, data_str))
        result = c.fetchone()
        return result['minutos_abonados'] if result and result['minutos_abonados'] is not None else 0

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
            data_str = current_date_iter.isoformat()
            
            # Pega a expectativa de trabalho
            expected_minutes = self.get_expected_daily_minutes(data_str, is_fichado, matricula) # Passa a matrícula

            # Pega o trabalho realizado
            c.execute("SELECT periodos, minutos_totais FROM horas_trabalhadas WHERE matricula=? AND data=?", (matricula, data_str))
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
        
        # Usa 'with' para garantir que o INSERT e o LOG estejam na mesma transação
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO horas_trabalhadas (matricula, data, minutos_totais, periodos) VALUES (?, ?, ?, ?)", (dados.get("matricula"), dados.get("data"), dados.get("minutos_totais"), json.dumps(dados.get("periodos"), default=str)))
            if justificativa != "Importação Automática" or old_data:
                self.log_edicao(dados.get("matricula"), dados.get("data"), periodos_antigos, json.dumps(dados.get("periodos"), default=str), justificativa)
    
    def log_edicao(self, matricula, data_ponto, periodos_antigos, periodos_novos, justificativa):
        # Esta função NÃO DEVE commitar. Ela participa da transação do chamador.
        self.conn.execute("INSERT INTO log_edicoes (matricula, data_ponto, periodos_antigos, periodos_novos, justificativa) VALUES (?, ?, ?, ?, ?)", (matricula, data_ponto, periodos_antigos, periodos_novos, justificativa))

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
            
            with self.conn: # Garante que o UPDATE e o LOG estejam na mesma transação
                self.conn.execute("UPDATE funcionarios SET fichado = ?, setor = ? WHERE matricula = ?", (fichado, setor, matricula))
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

    def _get_daily_summary_for_display(self, matricula, data_str):
        c = self.conn.cursor()
        # Usamos query parametrizada pura para evitar erros de nomes de colunas
        c.execute("SELECT * FROM horas_trabalhadas WHERE matricula=? AND data=?", (matricula, data_str))
        row = c.fetchone()
        if not row: return "00:00:00", "00:00:00"
        
        # Tentamos acessar por nome, se falhar, tentamos por índice
        try:
            total_worked = row['minutos_totais']
            periodos_json = row['periodos']
        except:
            total_worked = row[3]
            periodos_json = row[4]

        total_delay_penalty_minutes = 0
        try:
            periods = json.loads(periodos_json) if periodos_json else []
            for p in periods:
                total_delay_penalty_minutes += parse_hhmm_to_minutes(p.get('deducao_minutos', '00:00:00'))
        except:
            pass
        return total_worked, format_minutes_to_hms(total_delay_penalty_minutes)


    def get_point_panorama(self, start_date, end_date, target_matricula=None):
        """
        Retorna os dados do panorama para exibição na Treeview.

        REGRAS IMPORTANTES:
        - NÃO simula saldo em memória.
        - Lê banco_horas e extras_disponiveis DIRETAMENTE da tabela funcionarios.
        - Respeita o período informado.
        - Extrai E1/S1/E2/S2 do JSON 'periodos'.
        """
        try:
            if not start_date or not end_date:
                return []

            if isinstance(start_date, str):
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            else:
                start_date_obj = start_date

            if isinstance(end_date, str):
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            else:
                end_date_obj = end_date

            if end_date_obj < start_date_obj:
                start_date_obj, end_date_obj = end_date_obj, start_date_obj

            c = self.conn.cursor()

            funcionarios = []
            if target_matricula and str(target_matricula).strip() != "Todos":
                matricula_limpa = str(target_matricula).split(" - ")[0].strip()
                info = self.get_funcionario_info(matricula_limpa)
                if info:
                    funcionarios = [info]
            else:
                funcionarios = self.get_all_funcionarios()

            if not funcionarios:
                return []

            matriculas_list = [f["matricula"] for f in funcionarios if f and f.get("matricula")]
            if not matriculas_list:
                return []

            placeholders = ",".join(["?"] * len(matriculas_list))

            c.execute(f"""
                SELECT
                    matricula,
                    data,
                    minutos_totais,
                    periodos,
                    ignorar_atraso
                FROM horas_trabalhadas
                WHERE matricula IN ({placeholders})
                AND data BETWEEN ? AND ?
                ORDER BY matricula, data
            """, matriculas_list + [start_date_obj.isoformat(), end_date_obj.isoformat()])
            horas_rows = c.fetchall()

            work_map = {}
            for row in horas_rows:
                key = (row["matricula"], row["data"])
                work_map[key] = dict(row)

            panorama_final = []

            for func in funcionarios:
                matricula = func["matricula"]
                info_real = self.get_funcionario_info(matricula)

                current_date_iter = start_date_obj
                while current_date_iter <= end_date_obj:
                    data_str = current_date_iter.isoformat()

                    row = work_map.get((matricula, data_str))
                    e1 = ""
                    s1 = ""
                    e2 = ""
                    s2 = ""
                    carga_h = "00:00:00"
                    total_desconto = "00:00:00"
                    is_incomplete = False

                    if row:
                        carga_h = row.get("minutos_totais") or "00:00:00"

                        periodos_json = row.get("periodos") or "[]"
                        try:
                            periodos = json.loads(periodos_json)
                        except Exception:
                            periodos = []

                        horarios_extraidos = []
                        desconto_total_min = 0

                        for p in periodos:
                            entrada_str = p.get("entrada")
                            saida_str = p.get("saida")
                            deducao_str = p.get("deducao_minutos", "00:00:00")

                            desconto_total_min += parse_hhmm_to_minutes(deducao_str)

                            if entrada_str:
                                try:
                                    entrada_dt = try_parse_datetime(entrada_str)
                                    horarios_extraidos.append(entrada_dt.strftime("%H:%M") if entrada_dt else "")
                                except Exception:
                                    horarios_extraidos.append("")

                            if saida_str:
                                try:
                                    saida_dt = try_parse_datetime(saida_str)
                                    horarios_extraidos.append(saida_dt.strftime("%H:%M") if saida_dt else "")
                                except Exception:
                                    horarios_extraidos.append("")
                            else:
                                is_incomplete = True

                        if len(horarios_extraidos) > 0:
                            e1 = horarios_extraidos[0]
                        if len(horarios_extraidos) > 1:
                            s1 = horarios_extraidos[1]
                        if len(horarios_extraidos) > 2:
                            e2 = horarios_extraidos[2]
                        if len(horarios_extraidos) > 3:
                            s2 = horarios_extraidos[3]

                        total_desconto = format_minutes_to_hms(desconto_total_min)

                    ponto_dict = {
                        "Matricula": matricula,
                        "Nome": info_real.get("nome", ""),
                        "Data": data_str,
                        "E1": e1,
                        "S1": s1,
                        "E2": e2,
                        "S2": s2,
                        "Carga_Horaria": carga_h,
                        "Punicao": "00:00:00",
                        "Total_Desconto": total_desconto,
                        "BH_Anterior": "--",
                        "Extras_Anterior": "--",
                        "BH_Saldo": format_minutes_to_hms(info_real.get("banco_horas", 0) or 0),
                        "Extras_Disp": str(int(info_real.get("extras_disponiveis", 0) or 0)),
                        "is_incomplete": is_incomplete
                    }

                    panorama_final.append(ponto_dict)
                    current_date_iter += timedelta(days=1)

            panorama_final.sort(key=lambda x: (x["Nome"], x["Data"]))
            return panorama_final

        except Exception as e:
            print(f"Erro em get_point_panorama: {e}")
            return []
    
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

            # --- NOVA LÓGICA DE DEDUÇÃO INTELIGENTE ---
            
            # 1. Converte o saldo atual TODO para minutos
            # (Ex: 1 Extra e 10min vira 250 minutos totais)
            total_minutos_antes = (saldo_extras_antes * MINUTOS_UNIDADE_EXTRA) + saldo_bh_antes
            
            # 2. Converte o que está sendo pago/deduzido para minutos
            # (Ex: Pagar 1 Extra vira 240 minutos)
            total_minutos_deducao = (unidades_a_deduzir_extras * MINUTOS_UNIDADE_EXTRA) + minutos_a_deduzir_bh
            
            # 3. Realiza o abate do montante total
            total_minutos_novos = total_minutos_antes - total_minutos_deducao
            
            # 4. Redistribui o resultado para Extras e BH
            if total_minutos_novos < 0:
                # Se o saldo ficou negativo (Ex: -27 min), zeramos as Extras e o BH fica negativo
                novo_saldo_extras = 0
                novo_saldo_bh = total_minutos_novos
            else:
                # Se o saldo é positivo, recalculamos quantas Extras cheias cabem
                novo_saldo_extras = int(total_minutos_novos // MINUTOS_UNIDADE_EXTRA)
                novo_saldo_bh = total_minutos_novos % MINUTOS_UNIDADE_EXTRA
            
            # -----------------------------------------------------------

            with self.conn: # Garante que o UPDATE e o LOG estejam na mesma transação
                self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (novo_saldo_bh, novo_saldo_extras, matricula))

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


    def get_point_panorama(self, start_date, end_date, target_matricula=None):
        """
        Retorna os dados do panorama para exibição na Treeview.

        REGRAS IMPORTANTES:
        - NÃO simula saldo em memória.
        - Lê banco_horas e extras_disponiveis DIRETAMENTE da tabela funcionarios.
        - Respeita o período informado.
        - Extrai E1/S1/E2/S2 do JSON 'periodos'.
        """
        try:
            if not start_date or not end_date:
                return []

            if isinstance(start_date, str):
                start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
            else:
                start_date_obj = start_date

            if isinstance(end_date, str):
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            else:
                end_date_obj = end_date

            if end_date_obj < start_date_obj:
                start_date_obj, end_date_obj = end_date_obj, start_date_obj

            c = self.conn.cursor()

            funcionarios = []
            if target_matricula and str(target_matricula).strip() != "Todos":
                matricula_limpa = str(target_matricula).split(" - ")[0].strip()
                info = self.get_funcionario_info(matricula_limpa)
                if info:
                    funcionarios = [info]
            else:
                funcionarios = self.get_all_funcionarios()

            if not funcionarios:
                return []

            matriculas_list = [f["matricula"] for f in funcionarios if f and f.get("matricula")]
            if not matriculas_list:
                return []

            placeholders = ",".join(["?"] * len(matriculas_list))

            c.execute(f"""
                SELECT
                    matricula,
                    data,
                    minutos_totais,
                    periodos,
                    ignorar_atraso
                FROM horas_trabalhadas
                WHERE matricula IN ({placeholders})
                AND data BETWEEN ? AND ?
                ORDER BY matricula, data
            """, matriculas_list + [start_date_obj.isoformat(), end_date_obj.isoformat()])
            horas_rows = c.fetchall()

            work_map = {}
            for row in horas_rows:
                key = (row["matricula"], row["data"])
                work_map[key] = dict(row)

            panorama_final = []

            for func in funcionarios:
                matricula = func["matricula"]
                info_real = self.get_funcionario_info(matricula)

                current_date_iter = start_date_obj
                while current_date_iter <= end_date_obj:
                    data_str = current_date_iter.isoformat()

                    row = work_map.get((matricula, data_str))
                    e1 = ""
                    s1 = ""
                    e2 = ""
                    s2 = ""
                    carga_h = "00:00:00"
                    total_desconto = "00:00:00"
                    is_incomplete = False

                    if row:
                        carga_h = row.get("minutos_totais") or "00:00:00"

                        periodos_json = row.get("periodos") or "[]"
                        try:
                            periodos = json.loads(periodos_json)
                        except Exception:
                            periodos = []

                        horarios_extraidos = []
                        desconto_total_min = 0

                        for p in periodos:
                            entrada_str = p.get("entrada")
                            saida_str = p.get("saida")
                            deducao_str = p.get("deducao_minutos", "00:00:00")

                            desconto_total_min += parse_hhmm_to_minutes(deducao_str)

                            if entrada_str:
                                try:
                                    entrada_dt = try_parse_datetime(entrada_str)
                                    horarios_extraidos.append(entrada_dt.strftime("%H:%M") if entrada_dt else "")
                                except Exception:
                                    horarios_extraidos.append("")

                            if saida_str:
                                try:
                                    saida_dt = try_parse_datetime(saida_str)
                                    horarios_extraidos.append(saida_dt.strftime("%H:%M") if saida_dt else "")
                                except Exception:
                                    horarios_extraidos.append("")
                            else:
                                is_incomplete = True

                        if len(horarios_extraidos) > 0:
                            e1 = horarios_extraidos[0]
                        if len(horarios_extraidos) > 1:
                            s1 = horarios_extraidos[1]
                        if len(horarios_extraidos) > 2:
                            e2 = horarios_extraidos[2]
                        if len(horarios_extraidos) > 3:
                            s2 = horarios_extraidos[3]

                        total_desconto = format_minutes_to_hms(desconto_total_min)

                    ponto_dict = {
                        "Matricula": matricula,
                        "Nome": info_real.get("nome", ""),
                        "Data": data_str,
                        "E1": e1,
                        "S1": s1,
                        "E2": e2,
                        "S2": s2,
                        "Carga_Horaria": carga_h,
                        "Punicao": "00:00:00",
                        "Total_Desconto": total_desconto,
                        "BH_Anterior": "--",
                        "Extras_Anterior": "--",
                        "BH_Saldo": format_minutes_to_hms(info_real.get("banco_horas", 0) or 0),
                        "Extras_Disp": str(int(info_real.get("extras_disponiveis", 0) or 0)),
                        "is_incomplete": is_incomplete
                    }

                    panorama_final.append(ponto_dict)
                    current_date_iter += timedelta(days=1)

            panorama_final.sort(key=lambda x: (x["Nome"], x["Data"]))
            return panorama_final

        except Exception as e:
            print(f"Erro em get_point_panorama: {e}")
            return []

    
    def reprocess_daily_data(self, matricula):
        """
        Força o reprocessamento de cada dia importado usando a lógica de cálculo ATUAL.
        Isso corrige dias importados antes de atualizações de regras (ex: chegada antecipada).
        """
        c = self.conn.cursor()
        # Pega todos os dias desse funcionário
        c.execute("SELECT data, periodos, ignorar_atraso FROM horas_trabalhadas WHERE matricula=?", (matricula,))
        rows = c.fetchall()
        
        func_info = self.get_funcionario_info(matricula)
        setor = func_info.get('setor', 'N/D')

        with self.conn:
            for row in rows:
                data_str = row['data']
                ignorar_atraso = row['ignorar_atraso'] == 1
                try:
                    periodos_json = json.loads(row['periodos'])
                except: continue
                
                if not periodos_json: continue

                minutos_totais_novo = 0
                novos_periodos = []
                
                for i, p in enumerate(periodos_json):
                    entrada_str = p.get('entrada')
                    saida_str = p.get('saida')
                    
                    if not entrada_str: 
                        novos_periodos.append(p)
                        continue

                    ent = datetime.strptime(entrada_str, "%Y-%m-%d %H:%M:%S")
                    sai = datetime.strptime(saida_str, "%Y-%m-%d %H:%M:%S") if saida_str else None
                    
                    # RECALCULA usando a função global atualizada (que aceita chegada cedo)
                    # i*2 garante que o turno da tarde (index 1) vire turno_idx 2 (13:00)
                    _, liquido, deducao = calculate_period_data(ent, sai, data_str, i*2, setor, ignore_delay_flag=ignorar_atraso)
                    
                    minutos_totais_novo += liquido
                    
                    # Atualiza os detalhes no JSON para o relatório ficar correto também
                    p['minutos_liquidos'] = format_minutes_to_hms(liquido)
                    p['deducao_minutos'] = format_minutes_to_hms(deducao)
                    novos_periodos.append(p)

                # Salva o novo total calculado no Banco
                self.conn.execute("UPDATE horas_trabalhadas SET minutos_totais=?, periodos=? WHERE matricula=? AND data=?", 
                                  (format_minutes_to_hms(minutos_totais_novo), json.dumps(novos_periodos), matricula, data_str))
    
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
                data_str = current_sim_iter.isoformat()
                
                if current_sim_iter == SYSTEM_CURRENT_DATE:
                    current_sim_iter += timedelta(days=1)
                    continue
                
                expected_minutes = self.get_expected_daily_minutes(data_str, is_fichado, matricula)
                minutos_trabalhados_dia = work_map.get(data_str, {}).get('minutos', 0)
                excedente_dia = minutos_trabalhados_dia - expected_minutes
                saldo_bh_simulado += excedente_dia

                while saldo_bh_simulado >= MINUTOS_UNIDADE_EXTRA:
                    saldo_bh_simulado -= MINUTOS_UNIDADE_EXTRA
                    saldo_extras_simulado += 1
                while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                    saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                    saldo_extras_simulado -= 1

                punicao_do_dia = punicoes_map.get(data_str, 0)
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
            data_str = current_date_iter.isoformat()
            
            if current_date_iter == SYSTEM_CURRENT_DATE:
                 current_date_iter += timedelta(days=1)
                 continue

            # Pega expectativa (já com abono subtraído)
            expected_minutes = self.get_expected_daily_minutes(data_str, is_fichado, matricula)
            
            # Pega expectativa (sem abono) para contagem de faltas
            date_dt = current_date_iter
            expected_minutes_raw = 0
            if date_dt.weekday() != 6: # Não é Domingo
                is_holiday_today = self.is_holiday(data_str)
                if not (is_holiday_today and is_fichado): # Não é feriado para fichado
                    if date_dt.weekday() < 5: expected_minutes_raw = MINUTOS_JORNADA_SEG_SEX
                    elif date_dt.weekday() == 5: expected_minutes_raw = MINUTOS_JORNADA_SABADO
            
            dados_dia = work_map.get(data_str)
            minutos_trabalhados_dia = dados_dia.get('minutos', 0) if dados_dia else 0
            
            # Pega minutos abonados para estatística
            abono_min_dia = abonos_map.get(data_str, 0)
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

            punicao_do_dia = punicoes_map.get(data_str, 0)
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
            for line in f.readlines()[1:]:
                parts = re.split(r'\s+', line.strip())
                if len(parts) < 8: continue
                try:
                    matricula = str(parts[2]).zfill(8)
                    nome = str(parts[3]).strip()
                    dt_str = f"{parts[6]} {parts[7]}"
                    dt = try_parse_datetime(dt_str)
                    if dt and dt.date() >= datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                        unique_employees.add((matricula, nome))
                        employees_points_raw[matricula][dt.date().isoformat()].append({"datetime": dt})
                except: continue
    except Exception as e:
        logger(f"ERRO LEITURA: {e}"); return [], set()

    existing_matriculas = db_manager.get_all_funcionarios_matriculas()
    new_employees_list = [(m, n) for m, n in unique_employees if m not in existing_matriculas]
    processed_matriculas = set(m for m, n in unique_employees)

    for matricula, dias in sorted(employees_points_raw.items()):
        func_info = db_manager.get_funcionario_info(matricula)
        sector = func_info.get('setor', 'N/D') if func_info else 'N/D'

        for data, pontos_brutos in sorted(dias.items()):
            pontos_brutos.sort(key=lambda x: x["datetime"])
            periodos_trabalhados = []
            minutos_trabalhados_total = 0
            horarios = [p["datetime"] for p in pontos_brutos]

            i = 0
            while i < len(horarios):
                entrada = horarios[i]
                saida = horarios[i+1] if i + 1 < len(horarios) else None
                
                # USA A NOVA FUNÇÃO (Correção Iggor)
                bruto, liquido, deducao = calculate_period_data(entrada, saida, data, i, sector)
                
                if saida and saida < entrada: i += 2; continue

                minutos_trabalhados_total += liquido
                
                periodos_trabalhados.append({
                    "entrada": str(entrada),
                    "saida": str(saida) if saida else None,
                    "minutos_brutos": format_minutes_to_hms(bruto),
                    "deducao_minutos": format_minutes_to_hms(deducao),
                    "minutos_liquidos": format_minutes_to_hms(liquido)
                })
                i += 2 if saida else 1

            if periodos_trabalhados:
                # Mantém flag ignorar_atraso se existir
                db_manager.insert_horas_trabalhadas({
                    "matricula": matricula, "data": data,
                    "minutos_totais": format_minutes_to_hms(minutos_trabalhados_total),
                    "periodos": periodos_trabalhados
                })

    return new_employees_list, processed_matriculas

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
                            selectbackground=style_colors['ACCENT_COLOR'])

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
        self.root.title(f"WN Ponto Certo - {CURRENT_VERSION}")
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
    
    # Adicione dentro da class App
    def show_context_menu(self, event):
        item = self.tree_viewer.identify_row(event.y)
        if item:
            self.tree_viewer.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def toggle_ignore_delay_context(self):
        sel = self.tree_viewer.selection()
        if not sel: return
        
        # O iid é uma string composta (devido ao bind com DB), mas o values[0] tem a matricula
        vals = self.tree_viewer.item(sel[0], 'values')
        if not vals: return
        
        matricula = vals[0]
        data_ptbr = vals[2]
        
        try:
            data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        except: return
        
        if self.db.toggle_ignore_delay(matricula, data_db):
            self.append_log(f"Atraso ignorado/ativado para {matricula} em {data_db}. Recalculando...")
            self.db.recalculate_full_balance_for_employee(matricula)
            self.load_point_viewer(force_reload=True)
            messagebox.showinfo("Sucesso", "Status de atraso alterado!")
        else:
            messagebox.showerror("Erro", "Não há registros importados neste dia para alterar.")

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
            # Tenta usar a sintaxe nova, se falhar usa a antiga
            try:
                resample_method = PILImage.LANCZOS 
            except AttributeError:
                resample_method = Image.LANCZOS
                
            logo_img = logo_img.resize((45, 45), resample_method)
            self.logo_photo = ImageTk.PhotoImage(logo_img)
            logo_label = tk.Label(header_frame, image=self.logo_photo, bg="#0a192f")
            logo_label.pack(side=tk.LEFT, padx=(0, 10))
        except Exception as e:
            print(f"ERRO logo: {e}")
        app_title = tk.Label(header_frame, text="WN Ponto Certo", font=("Segoe UI", 20, "bold"), fg="white", bg="#0a192f")
        app_title.pack(side=tk.LEFT)

        # --- Frame de Ações dividido em duas linhas ---
        actions_frame_container = tk.Frame(top_frame, bg="#0a192f")
        actions_frame_container.pack(fill=tk.X, pady=(10,0))

        # --- Botões da Direita (Sair, Atualizar) ---
        right_buttons_frame = tk.Frame(actions_frame_container, bg="#0a192f")
        right_buttons_frame.pack(side=tk.RIGHT, anchor='n', padx=(10, 0)) 
        
        ttk.Button(right_buttons_frame, text="🔄 Verificar Atualizações", command=self.check_for_updates).pack(side=tk.TOP, fill=tk.X, pady=(0,5))
        ttk.Button(right_buttons_frame, text="🚪 Sair", command=self.on_app_close, style='TButton').pack(side=tk.TOP, fill=tk.X)

        # --- Botões da Esquerda (Duas fileiras) ---
        left_buttons_frame = tk.Frame(actions_frame_container, bg="#0a192f")
        left_buttons_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Fileira 1
        actions_frame_row1 = tk.Frame(left_buttons_frame, bg="#0a192f")
        actions_frame_row1.pack(fill=tk.X)
        
        ttk.Button(actions_frame_row1, text="📂 Importar", command=self.on_import, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row1, text="✏️ Editar Func", command=self.on_edit_employee, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row1, text="📅 Feriados", command=self.on_manage_holidays, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row1, text="💰 Pagar Saldo", command=self.on_extra_payment, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row1, text="↩️ Desfazer Pagamento", command=self.on_reverse_payment, style='Delete.TButton').pack(side=tk.LEFT, padx=(0, 10))
        
        # Fileira 2
        actions_frame_row2 = tk.Frame(left_buttons_frame, bg="#0a192f")
        actions_frame_row2.pack(fill=tk.X, pady=(5,0)) 

        ttk.Button(actions_frame_row2, text="⚖️ Punição", command=self.on_add_punishment, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="🔢 Saldos Iniciais", command=self.on_edit_initial_balance, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="✅ Abonar Falta", command=self.on_abone_falta, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        
        # --- NOVO BOTÃO AQUI ---
        ttk.Button(actions_frame_row2, text="⏳ Abonar Atraso", command=self.toggle_ignore_delay_context, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        # -----------------------

        ttk.Button(actions_frame_row2, text="📊 Relatório Detalhado", command=self.on_detailed_report, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame_row2, text="📄 Exportar Log", command=self.on_export_log, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        
        log_frame = ttk.LabelFrame(main_frame, text=" Log ", style='TLabelframe')
        log_frame.grid(row=1, column=1, sticky="nsew", pady=5, padx=(5, 0))
        self.log_area = scrolledtext.ScrolledText(log_frame, bg="#112240", fg="#a8b2d1", insertbackground="white", font=("Consolas", 9), relief=tk.FLAT, borderwidth=5)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        self.setup_point_viewer(main_frame)

    def show_context_menu(self, event):
        item = self.tree_viewer.identify_row(event.y)
        if item:
            self.tree_viewer.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def toggle_ignore_delay_context(self):
        sel = self.tree_viewer.selection()
        if not sel: 
            messagebox.showwarning("Seleção Necessária", "Por favor, selecione um dia na tabela abaixo para abonar o atraso.")
            return
        
        vals = self.tree_viewer.item(sel[0], 'values')
        if not vals: return
        
        matricula = vals[0]
        data_ptbr = vals[2]
        
        try:
            data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        except: return
        
        # Chama a função do banco que altera o status 'ignorar_atraso'
        if self.db.toggle_ignore_delay(matricula, data_db):
            self.append_log(f"Status de atraso alterado para {matricula} em {data_db}. Recalculando...")
            # Recalcula o saldo total
            self.db.recalculate_full_balance_for_employee(matricula)
            # Recarrega a tela para mostrar os novos valores (sem a multiplicação)
            self.load_point_viewer(force_reload=True)
            messagebox.showinfo("Sucesso", "Status de atraso alterado! A multiplicação foi removida/adicionada para este dia.")
        else:
            messagebox.showerror("Erro", "Não há registros importados neste dia para alterar.")
            
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
        win = tk.Toplevel(self.root); win.title("Adicionar/Remover Punição")
        win.configure(bg=self.BG_COLOR);
        win.state('zoomed'); win.minsize(1024, 768) # Aumenta o tamanho
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Frame do Formulário (Esquerda) ---
        form_frame = ttk.LabelFrame(main_frame, text=" Adicionar Punição ", style='TLabelframe')
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
        cal_punicao = Calendar(form_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR',
                               background="#008080", foreground="white", headersbackground="#008080",
                               mindate=min_date)
        cal_punicao.pack(anchor="w", pady=(0, 15), padx=10)
        
        tk.Label(form_frame, text="3. Tempo (HH:MM):", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        entry_tempo = ttk.Entry(form_frame, width=15)
        entry_tempo.pack(anchor="w", padx=10, pady=(0, 15))

        tk.Label(form_frame, text="4. Motivo:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        entry_motivo = ttk.Entry(form_frame, width=30)
        entry_motivo.pack(anchor="w", fill="x", pady=(0, 20), padx=10)

        btn_salvar_punicao = ttk.Button(form_frame, text="✅ Registrar Punição", style='TButton')
        btn_salvar_punicao.pack(pady=10, padx=10, fill=tk.X)

        btn_delete = ttk.Button(form_frame, text="🗑️ Remover Punição Selecionada", style='Delete.TButton')
        btn_delete.pack(pady=(15, 5), padx=10, fill=tk.X)

        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy).pack(side=tk.BOTTOM, pady=10, padx=10, fill=tk.X)

        # --- Frame da Lista (Direita) ---
        list_frame = ttk.LabelFrame(main_frame, text=" Punições Registradas (no período) ", style='TLabelframe')
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        tree_columns = ("Data", "Tempo", "Motivo")
        tree_punicoes = ttk.Treeview(list_frame, columns=tree_columns, show="headings", selectmode="browse")

        v_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree_punicoes.yview)
        tree_punicoes.configure(yscrollcommand=v_scroll.set)
        tree_punicoes.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')

        tree_punicoes.heading("Data", text="Data")
        tree_punicoes.column("Data", width=100, anchor=tk.CENTER)
        tree_punicoes.heading("Tempo", text="Tempo")
        tree_punicoes.column("Tempo", width=100, anchor=tk.CENTER)
        tree_punicoes.heading("Motivo", text="Motivo")
        tree_punicoes.column("Motivo", width=250, anchor=tk.W, stretch=tk.YES)

        # --- Funções de Lógica da Janela ---

        def refresh_punicao_list():
            [tree_punicoes.delete(i) for i in tree_punicoes.get_children()]
            selection = cmb_func.get()
            if not selection:
                return
            
            matricula = selection.split(" - ")[0]
            # Usa as datas da tela principal (como a tela de abono faz)
            start_date = self.selected_start_date
            end_date = self.selected_end_date
            
            if not start_date or not end_date:
                start_date = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
                end_date = date.today()

            punishments = self.db.get_punishments_in_range(matricula, start_date, end_date)
            for i, p in enumerate(punishments):
                try:
                    data_fmt = datetime.strptime(p['data_punicao'], '%Y-%m-%d').strftime('%d/%m/%Y')
                except:
                    data_fmt = p['data_punicao']
                
                minutos_hms = format_minutes_to_hms(p.get('minutos_descontados', 0))
                values = (data_fmt, minutos_hms, p['motivo'])
                iid = f"punicao_{p['id']}" # Armazena o ID aqui
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree_punicoes.insert("", "end", values=values, iid=iid, tags=(tag,))

        def save_punishment():
             selection = cmb_func.get();
             if not selection: messagebox.showerror("Erro", "Funcionário não selecionado.", parent=win); return
             matricula = selection.split(" - ")[0]; nome_func = " ".join(selection.split(" - ")[1:])
             data_str = cal_punicao.get_date(); tempo_str = entry_tempo.get().strip(); motivo = entry_motivo.get().strip()

             if data_str < SYSTEM_START_DATE:
                 messagebox.showerror("Erro", f"Não é possível registrar punições antes de {SYSTEM_START_DATE}.", parent=win)
                 return

             if not tempo_str: messagebox.showerror("Erro", "Tempo obrigatório.", parent=win); return
             if not motivo: messagebox.showerror("Erro", "Motivo obrigatório.", parent=win); return

             minutos_descontados = parse_hhmm_to_minutes(tempo_str)
             if minutos_descontados == 0:
                  messagebox.showerror("Erro", "Formato de tempo inválido (use HH:MM) ou tempo é zero.", parent=win); return
             if minutos_descontados < 0:
                 minutos_descontados = abs(minutos_descontados)

             confirm_msg = (f"Confirmar {format_minutes_to_hms(minutos_descontados)} para {nome_func}\nData: {datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')}?\nMotivo: {motivo}\n\nATENÇÃO: A punição será registrada e o saldo recalculado.")
             if messagebox.askyesno("Confirmar Punição", confirm_msg, parent=win):
                 if self.db.add_punicao(matricula, data_str, minutos_descontados, motivo):
                     messagebox.showinfo("Sucesso", "Punição registrada! O saldo será recalculado.", parent=win)
                     self.append_log(f"PUNIÇÃO REGISTRADA: {matricula} - {data_str} - {format_minutes_to_hms(minutos_descontados)} - {motivo}")
                     entry_tempo.delete(0, 'end'); entry_motivo.delete(0, 'end')
                     try:
                         self.db.recalculate_full_balance_for_employee(matricula)
                         self.append_log(f"Recalculando saldo para {matricula} após registro de punição.")
                     except Exception as e:
                         self.append_log(f"ERRO ao recalcular saldo para {matricula} após punição: {e}")
                         messagebox.showerror("Erro Recálculo", f"Erro ao recalcular saldo para {matricula}:\n{e}", parent=win)
                     
                     refresh_punicao_list() # Atualiza a lista na tela
                     self.load_point_viewer(force_reload=True);
                     self._update_calendar_tags()
                 else: messagebox.showerror("Erro", "Não foi possível salvar a punição.", parent=win)
        
        def delete_selected_punishment():
            selected_iid = tree_punicoes.selection()
            if not selected_iid:
                messagebox.showerror("Erro", "Nenhuma punição selecionada na lista.", parent=win)
                return

            iid = selected_iid[0]
            if not iid.startswith('punicao_'):
                return
                
            item_data = tree_punicoes.item(iid, 'values')
            desc = f"{item_data[0]} ({item_data[1]}) - {item_data[2]}"
            punicao_id = iid.split('_')[1]

            if not messagebox.askyesno("Confirmar Remoção", f"Tem certeza que deseja remover a punição:\n{desc}\n\nO saldo será recalculado.", parent=win):
                return

            matricula_afetada = self.db.delete_punicao(punicao_id) # Chama a nova função
            if matricula_afetada:
                self.append_log(f"PUNIÇÃO REMOVIDA: {desc}. Recalculando...")
                try:
                    self.db.recalculate_full_balance_for_employee(matricula_afetada)
                    self.append_log(f"Recálculo de {matricula_afetada} concluído.")
                    messagebox.showinfo("Sucesso", "Punição removida e saldo recalculado!", parent=win)
                    refresh_punicao_list() # Atualiza a lista
                    self.load_point_viewer(force_reload=True) # Atualiza a tela principal
                except Exception as e:
                    messagebox.showerror("Erro", f"Erro ao recalcular: {e}", parent=win)
                    self.append_log(f"ERRO ao recalcular {matricula_afetada} após remover punição: {e}")
            else:
                messagebox.showerror("Erro", "Não foi possível remover a punição.", parent=win)

        # --- Conectar Funções aos Botões ---
        cmb_func.bind("<<ComboboxSelected>>", lambda e: refresh_punicao_list())
        btn_salvar_punicao.config(command=save_punishment)
        btn_delete.config(command=delete_selected_punishment)
        
        # Carrega a lista se um funcionário já estiver selecionado na tela principal
        if self.cmb_filter_func.get() and self.cmb_filter_func.get() != "Todos":
            cmb_func.set(self.cmb_filter_func.get())
            refresh_punicao_list()

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

                # --- REMOÇÃO: Bloco de "Zerar Banco de Horas" foi removido daqui ---

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

                # --- REMOÇÃO: Bloco de "Zerar Banco de Horas" foi removido daqui ---

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

                if not messagebox.askyesno("Confirmar Pagamento", msg_confirm):
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

        tk.Label(form_frame, text="1. Func:", bg="#0a192f", fg="#ccd6f6", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); 
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]; 
        cmb_func = ttk.Combobox(form_frame, values=nomes, state="readonly", width=50); 
        cmb_func.pack(anchor="w", pady=(0, 20)); 
        tk.Label(form_frame, text="2. Período:", bg="#0a192f", fg="#ccd6f6", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))

        date_picker = DateRangePicker(form_frame, self.BG_COLOR, self.style_colors_dict)
        date_picker.pack(pady=10, padx=10)
        
        if self.selected_start_date:
            date_picker.cal.selection_set(self.selected_start_date)
            date_picker._on_calendar_click()
        if self.selected_end_date:
            date_picker.cal.selection_set(self.selected_end_date)
            date_picker._on_calendar_click()
        
        btn_export = ttk.Button(form_frame, text="Gerar PDF", style='TButton'); 
        btn_export.pack(pady=20)
        
        def generate_pdf():
            selection = cmb_func.get();
            if not selection: 
                messagebox.showerror("Erro", "Funcionário não selecionado.", parent=win); return
            
            matricula = selection.split(" - ")[0]; 
            nome_func = " ".join(selection.split(" - ")[1:])
            
            start_dt, end_dt = date_picker.get_dates()

            try:
                if not start_dt or not end_dt:
                    messagebox.showerror("Erro", "Selecione um período válido (Início e Fim).", parent=win)
                    return
                
                if end_dt < start_dt:
                    messagebox.showerror("Erro", "Data final não pode ser anterior à data inicial.", parent=win)
                    return
                if start_dt < datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date():
                    messagebox.showerror("Erro", f"Data de início não pode ser anterior a {SYSTEM_START_DATE}.", parent=win)
                    return
            except Exception as e:
                messagebox.showerror("Erro", f"Datas inválidas: {e}", parent=win)
                return

            logs = self.db.get_logs_for_period(matricula, start_dt, end_dt)
            if not logs: 
                messagebox.showinfo("Aviso", "Nenhum log encontrado.", parent=win); return

            filepath = filedialog.asksaveasfilename(
                defaultextension=".pdf", 
                filetypes=[("PDF files", "*.pdf")], 
                title="Salvar Relatório", 
                initialfile=f"Log_{nome_func.replace(' ','_')}_{start_dt.isoformat()}_a_{end_dt.isoformat()}.pdf"
            )
            if not filepath: 
                return
            
            try:
                doc = SimpleDocTemplate(filepath, pagesize=landscape(A4), rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm); 
                styles = getSampleStyleSheet(); 
                story = []
                
                style_table_header = ParagraphStyle(
                    name='TableHeader',
                    parent=styles['Normal'],
                    fontName='Helvetica-Bold',
                    textColor=colors.whitesmoke,
                    alignment=TA_CENTER
                )
                style_cell_left = ParagraphStyle(
                    name='TableCellLeft',
                    parent=styles['Normal'],
                    fontSize=8,
                    textColor=colors.black,
                    alignment=TA_LEFT
                )
                style_cell_center = ParagraphStyle(
                    name='TableCellCenter',
                    parent=styles['Normal'],
                    fontSize=8,
                    textColor=colors.black,
                    alignment=TA_CENTER
                )
                
                story.append(Paragraph("Relatório Log Alterações", styles['h1'])); 
                story.append(Spacer(1, 0.5*cm)); 
                story.append(Paragraph(f"<b>Funcionário:</b> {nome_func}", styles['Normal'])); 
                story.append(Paragraph(f"<b>Matrícula:</b> {matricula}", styles['Normal'])); 
                story.append(Paragraph(f"<b>Período:</b> {start_dt.strftime('%d/%m/%Y')} a {end_dt.strftime('%d/%m/%Y')}", styles['Normal'])); 
                story.append(Spacer(1, 1*cm))
                
                col_headers = ['Data Ponto', 'Data Edição', 'Valor Antigo', 'Valor Novo', 'Justificativa']
                table_data = [[Paragraph(h, style_table_header) for h in col_headers]]
                
                for log in logs:
                    row = [
                        Paragraph(datetime.strptime(log['data_ponto'], '%Y-%m-%d').strftime('%d/%m/%Y'), style_cell_center), 
                        Paragraph(datetime.strptime(log['data_edicao'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M'), style_cell_center), 
                        Paragraph(log['periodos_antigos'], style_cell_left), 
                        Paragraph(log['periodos_novos'], style_cell_left), 
                        Paragraph(log['justificativa'], style_cell_center)
                    ]
                    table_data.append(row)
                
                t = Table(table_data, colWidths=[2.5*cm, 3.0*cm, 8.0*cm, 8.0*cm, 4.0*cm]); 
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.teal), 
                    ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), 
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'), 
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), 
                    ('BOTTOMPADDING', (0,0), (-1,0), 12), 
                    ('BACKGROUND', (0,1), (-1,-1), colors.beige), 
                    ('GRID', (0,0), (-1,-1), 1, colors.black),
                    ('VALIGN', (0,0), (-1,-1), 'TOP')
                ]))
                story.append(t); 
                doc.build(story); 
                messagebox.showinfo("Sucesso", f"Relatório salvo:\n{filepath}", parent=win); 
                win.destroy()
            except Exception as e: 
                messagebox.showerror("Erro PDF", f"Erro: {e}", parent=win)
        
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
                data_str = data_dt.isoformat()
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
            
            if data_str < SYSTEM_START_DATE:
                 messagebox.showerror("Erro", f"Não é possível abonar dias antes de {SYSTEM_START_DATE}.", parent=win)
                 return

            confirm_msg = f"Confirmar abono de {format_minutes_to_hms(minutos_abonados)} para {nome} em {data_dt.strftime('%d/%m/%Y')}?\nMotivo: {motivo}\n\nO saldo será recalculado."
            if not messagebox.askyesno("Confirmar Abono", confirm_msg, parent=win):
                return
            
            if self.db.add_abono(matricula, data_str, motivo, minutos_abonados): # <-- PARÂMETRO ADICIONADO
                self.append_log(f"ABONO REGISTRADO: {matricula} - {data_str} - {format_minutes_to_hms(minutos_abonados)} - {motivo}. Recalculando...")
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
    
    def on_reverse_payment(self):
        win = tk.Toplevel(self.root); win.title("Desfazer (Estornar) Pagamento")
        win.configure(bg=self.BG_COLOR); win.state('zoomed'); win.minsize(1024, 768)
        win.resizable(False, False); win.transient(self.root); win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Frame do Formulário (Esquerda) ---
        form_frame = ttk.LabelFrame(main_frame, text=" Filtros ", style='TLabelframe')
        form_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        tk.Label(form_frame, text="1. Func:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 5), padx=10)
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]
        cmb_func = ttk.Combobox(form_frame, values=nomes, state="readonly", width=40)
        cmb_func.pack(anchor="w", pady=(0, 15), padx=10)

        tk.Label(form_frame, text="2. Período do Log:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5), padx=10)
        
        date_picker = DateRangePicker(form_frame, self.BG_COLOR, self.style_colors_dict)
        date_picker.pack(pady=10, padx=10)
        
        # --- MODIFICAÇÃO: Definindo um período padrão sensato (Mês Atual) ---
        try:
            min_date_system = datetime.strptime(SYSTEM_START_DATE, "%Y-%m-%d").date()
        except:
            min_date_system = date.today()

        today = date.today()
        start_of_month = today.replace(day=1)
        
        # O início é o começo do mês ou o início do sistema (o que for mais recente)
        default_start_date = max(start_of_month, min_date_system)
        default_end_date = today

        # Define as datas internas diretamente
        date_picker.cal.selection_set(default_start_date)
        date_picker.selected_start_date = default_start_date
        date_picker.lbl_start.config(text=default_start_date.strftime("%d/%m/%Y"))
        
        date_picker.cal.selection_set(default_end_date)
        date_picker.selected_end_date = default_end_date
        date_picker.lbl_end.config(text=default_end_date.strftime("%d/%m/%Y"))
        
        date_picker.selecting_start = True
        date_picker._update_calendar_tags()
        # --- FIM DA MODIFICAÇÃO ---

        btn_refresh = ttk.Button(form_frame, text="Atualizar Lista", style='TButton')
        btn_refresh.pack(pady=(10, 5), padx=10, fill=tk.X)

        btn_delete = ttk.Button(form_frame, text="↩️ Desfazer Pagamento Selecionado", style='Delete.TButton')
        btn_delete.pack(pady=(5, 5), padx=10, fill=tk.X)

        ttk.Button(form_frame, text="Sair", style='Delete.TButton', command=win.destroy).pack(side=tk.BOTTOM, pady=10, padx=10, fill=tk.X)

        # --- Frame da Lista (Direita) ---
        list_frame = ttk.LabelFrame(main_frame, text=" Pagamentos Registrados (no período) ", style='TLabelframe')
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        tree_columns = ("Data", "Valor Antigo", "Valor Novo")
        tree_logs = ttk.Treeview(list_frame, columns=tree_columns, show="headings", selectmode="browse")

        v_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree_logs.yview)
        tree_logs.configure(yscrollcommand=v_scroll.set)
        tree_logs.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')

        tree_logs.heading("Data", text="Data Pagamento")
        tree_logs.column("Data", width=100, anchor=tk.CENTER)
        tree_logs.heading("Valor Antigo", text="Saldos Antigos")
        tree_logs.column("Valor Antigo", width=200, anchor=tk.W)
        tree_logs.heading("Valor Novo", text="Saldos Novos")
        tree_logs.column("Valor Novo", width=200, anchor=tk.W, stretch=tk.YES)

        # --- Funções de Lógica da Janela ---

        def refresh_payment_logs():
            [tree_logs.delete(i) for i in tree_logs.get_children()]
            selection = cmb_func.get()
            if not selection:
                return
            
            matricula = selection.split(" - ")[0]
            start_date, end_date = date_picker.get_dates()
            
            if not start_date or not end_date:
                messagebox.showwarning("Aviso", "Selecione um período de início e fim.", parent=win)
                return

            payment_logs = self.db.get_payment_logs(matricula, start_date, end_date)
            
            for i, log in enumerate(payment_logs):
                try:
                    data_fmt = datetime.strptime(log['data_ponto'], '%Y-%m-%d').strftime('%d/%m/%Y')
                except:
                    data_fmt = log['data_ponto']
                
                values = (data_fmt, log['periodos_antigos'], log['periodos_novos'])
                iid = f"log_{log['id']}" # Armazena o ID do log
                tag = 'evenrow' if i % 2 == 0 else 'oddrow'
                tree_logs.insert("", "end", values=values, iid=iid, tags=(tag,))

        def execute_reversal():
            selected_iid = tree_logs.selection()
            if not selected_iid:
                messagebox.showerror("Erro", "Nenhum log de pagamento selecionado na lista.", parent=win)
                return

            iid = selected_iid[0]
            if not iid.startswith('log_'):
                return
                
            item_data = tree_logs.item(iid, 'values')
            desc = f"Data: {item_data[0]}\nDe: {item_data[1]}\nPara: {item_data[2]}"
            log_id = iid.split('_')[1]

            if not messagebox.askyesno("Confirmar Estorno", f"Tem certeza que deseja ESTORNAR (desfazer) este pagamento?\n\n{desc}\n\nO saldo do funcionário será recalculado.", parent=win):
                return

            success, message = self.db.reverse_payment(log_id)
            
            if success:
                matricula_afetada = message
                self.append_log(f"ESTORNO REALIZADO: Log {log_id}. Recalculando {matricula_afetada}...")
                try:
                    self.db.recalculate_full_balance_for_employee(matricula_afetada)
                    self.append_log(f"Recálculo de {matricula_afetada} concluído.")
                    messagebox.showinfo("Sucesso", "Pagamento estornado e saldo recalculado!", parent=win)
                    refresh_payment_logs() # Atualiza a lista
                    self.load_point_viewer(force_reload=True) # Atualiza a tela principal
                except Exception as e:
                    messagebox.showerror("Erro", f"Erro ao recalcular: {e}", parent=win)
                    self.append_log(f"ERRO ao recalcular {matricula_afetada} após estorno: {e}")
            else:
                messagebox.showerror("Erro", f"Não foi possível estornar o pagamento:\n{message}", parent=win)
                self.append_log(f"ERRO ao estornar log {log_id}: {message}")

        # --- Conectar Funções ---
        cmb_func.bind("<<ComboboxSelected>>", lambda e: refresh_payment_logs())
        date_picker.cal.bind("<<CalendarSelected>>", date_picker._on_calendar_click)
        btn_refresh.config(command=refresh_payment_logs)
        btn_delete.config(command=execute_reversal)
        
        # Carrega a lista da tela principal se houver um funcionário
        if self.cmb_filter_func.get() and self.cmb_filter_func.get() != "Todos":
            cmb_func.set(self.cmb_filter_func.get())
            refresh_payment_logs() # Agora deve funcionar na carga inicial

    def on_recalculate_and_refresh(self):
        """
        Reprocessa os dias do funcionário selecionado (ou de todos),
        recalcula o saldo integral, força gravação no banco e atualiza a interface.
        """
        try:
            self.append_log("Iniciando recálculo forçado e sincronização de saldos...")

            target_str = (self.cmb_filter_func.get() or "").strip()
            total_processados = 0
            total_erros = 0

            if not target_str or target_str == "Todos":
                funcionarios = self.db.get_all_funcionarios()
                if not funcionarios:
                    messagebox.showwarning("Aviso", "Nenhum funcionário encontrado para recalcular.")
                    return

                for emp in funcionarios:
                    matricula = emp["matricula"]
                    try:
                        self.append_log(f"Reprocessando dias de {matricula}...")
                        self.db.reprocess_daily_data(matricula)

                        self.append_log(f"Recalculando saldo total de {matricula}...")
                        ok = self.db.recalculate_full_balance_for_employee(matricula)
                        if not ok:
                            raise Exception("Recalculate retornou False")

                        info_final = self.db.get_funcionario_info(matricula)
                        self.append_log(
                            f"OK {matricula} | "
                            f"BH: {format_minutes_to_hms(info_final.get('banco_horas', 0) or 0)} | "
                            f"Extras: {int(info_final.get('extras_disponiveis', 0) or 0)}"
                        )
                        total_processados += 1

                    except Exception as e:
                        total_erros += 1
                        self.append_log(f"ERRO ao recalcular {matricula}: {e}")

                if total_erros == 0:
                    msg = f"Saldos de {total_processados} funcionário(s) atualizados com sucesso."
                    self.append_log("Recálculo concluído com sucesso.")
                    messagebox.showinfo("Sucesso", msg)
                else:
                    msg = (
                        f"Recálculo concluído com alertas.\n\n"
                        f"Processados com sucesso: {total_processados}\n"
                        f"Erros: {total_erros}\n\n"
                        f"Verifique o log para detalhes."
                    )
                    self.append_log("Recálculo concluído com erros parciais.")
                    messagebox.showwarning("Atenção", msg)

            else:
                matricula = target_str.split(" - ")[0].strip()

                self.append_log(f"Reprocessando dias de {matricula}...")
                self.db.reprocess_daily_data(matricula)

                self.append_log(f"Recalculando saldo total de {matricula}...")
                ok = self.db.recalculate_full_balance_for_employee(matricula)
                if not ok:
                    raise Exception("Recalculate retornou False")

                info_final = self.db.get_funcionario_info(matricula)
                self.append_log(
                    f"OK {matricula} | "
                    f"BH: {format_minutes_to_hms(info_final.get('banco_horas', 0) or 0)} | "
                    f"Extras: {int(info_final.get('extras_disponiveis', 0) or 0)}"
                )

                self.append_log("Recálculo concluído com sucesso.")
                messagebox.showinfo(
                    "Sucesso",
                    f"Saldos de {target_str} atualizados!\n\n"
                    f"BH: {format_minutes_to_hms(info_final.get('banco_horas', 0) or 0)}\n"
                    f"Extras: {int(info_final.get('extras_disponiveis', 0) or 0)}"
                )

            self.load_point_viewer(force_reload=True)
            self._update_calendar_tags()

        except Exception as e:
            self.append_log(f"ERRO geral no recálculo: {e}")
            messagebox.showerror("Erro", f"Falha ao recalcular saldos.\n\nDetalhes: {e}")


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

        # Calendário
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
                                      selectbackground=self.ACCENT_COLOR, mindate=min_date)

        self.main_calendar.grid(row=0, column=0, rowspan=2, padx=(0, 20), sticky='n')
        self.main_calendar.bind("<<CalendarSelected>>", self.on_calendar_click)
        self.main_calendar.bind("<<CalendarMonthChanged>>", self.on_calendar_month_changed)
        
        # Tags do calendário
        self.main_calendar.tag_config('start_date', background=self.START_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('end_date', background=self.END_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('range_date', background=self.RANGE_BG_COLOR, foreground='#ccd6f6')
        self.main_calendar.tag_config('holiday', background=self.HOLIDAY_COLOR, foreground='white')

        # Labels de Período
        period_frame = tk.Frame(calendar_frame, bg="#0a192f")
        period_frame.grid(row=0, column=1, columnspan=2, sticky='nw', padx=5)
        tk.Label(period_frame, text="Período:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        start_frame = tk.Frame(period_frame, bg="#0a192f"); start_frame.pack(anchor='w', pady=2)
        tk.Label(start_frame, text="Início:", bg="#0a1f2f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_start = tk.Label(start_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_start.pack(side=tk.LEFT)
        end_frame = tk.Frame(period_frame, bg="#0a192f"); end_frame.pack(anchor='w', pady=2)
        tk.Label(end_frame, text="Fim:", bg="#0a192f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_end = tk.Label(end_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_end.pack(side=tk.LEFT)

        # Listas de Feriados e Punições
        holiday_frame = tk.Frame(calendar_frame, bg=self.BG_COLOR)
        holiday_frame.grid(row=1, column=1, sticky='nsew', padx=5, pady=(10,0))
        tk.Label(holiday_frame, text="Feriados:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 2))
        holiday_list_frame = tk.Frame(holiday_frame, bg=self.BG_COLOR); holiday_list_frame.pack(fill=tk.BOTH, expand=True)
        self.holiday_listbox = tk.Listbox(holiday_list_frame, bg=self.LIGHT_BG, fg=self.FG_COLOR, height=3)
        self.holiday_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        punishment_frame = tk.Frame(calendar_frame, bg=self.BG_COLOR)
        punishment_frame.grid(row=1, column=2, sticky='nsew', padx=5, pady=(10,0))
        tk.Label(punishment_frame, text="Punições:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 2))
        punishment_list_frame = tk.Frame(punishment_frame, bg=self.BG_COLOR); punishment_list_frame.pack(fill=tk.BOTH, expand=True)
        self.punishment_listbox = tk.Listbox(punishment_list_frame, bg=self.LIGHT_BG, fg=self.FG_COLOR, height=3)
        self.punishment_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lbl_total_punishments = tk.Label(punishment_frame, text="Total Punições: --", bg="#0a192f", fg=self.FG_COLOR, font=('Segoe UI', 9))
        self.lbl_total_punishments.pack(anchor='w', pady=(2, 0))

        # Labels de Saldos
        frame_saldos = ttk.LabelFrame(frame_viewer, text=" Saldos Atuais", style='TLabelframe')
        frame_saldos.grid(row=2, column=0, sticky="ew", pady=(10, 5), padx=10)
        tk.Label(frame_saldos, text="BH:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(10,0)); self.lbl_saldo_bh_total = tk.Label(frame_saldos, text="--:--:--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_saldo_bh_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Extras:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_saldo_extras_total = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_saldo_extras_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Fichado:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_fichado_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_fichado_status.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Setor:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_setor_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_setor_status.pack(side=tk.LEFT, padx=5)

        # Treeview (Tabela)
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

        # --- AQUI ESTÁ A CORREÇÃO: CRIAÇÃO DO MENU DEPOIS DA TREEVIEW ---
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Desconsiderar Atraso (Alternar)", command=self.toggle_ignore_delay_context)
        self.tree_viewer.bind("<Button-3>", self.show_context_menu)
        # -------------------------------------------------------------

        col_widths = {"Matrícula": 80, "Nome": 220, "Data": 80, "E1": 60, "S1": 60, "E2": 60, "S2": 60, "Carga_Horaria": 90, "Punição": 80, "Total_Desconto": 100}
        for col in columns:
            self.tree_viewer.heading(col, text=col.replace('_', ' '))
            self.tree_viewer.column(col, width=col_widths.get(col, 100))

        self.tree_viewer.bind('<ButtonRelease-1>', self.start_in_place_edit)
        self.tree_viewer.tag_configure('evenrow', background='#112240')
        self.tree_viewer.tag_configure('oddrow', background='#172a45')
        self.tree_viewer.tag_configure('incomplete', foreground='#FF6B6B')

        self.update_employee_filter()


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
            if not messagebox.askyesno("Atualizar", "Alterações não salvas serão perdidas. Continuar?"): return
            self.unsaved_edits = {}
            
        start_date = self.selected_start_date
        end_date = self.selected_end_date
        selected_func = self.cmb_filter_func.get()
        target_matricula = selected_func.split(" - ")[0] if selected_func != "Todos" else None

        # Limpa visualização
        [self.tree_viewer.delete(i) for i in self.tree_viewer.get_children()]
        
        if not start_date or not end_date: return

        try:
            panorama_data = self.db.get_point_panorama(start_date, end_date, target_matricula)
            
            for i, item in enumerate(panorama_data):
                data_db_str = item['Data']
                data_ptbr = datetime.strptime(data_db_str, "%Y-%m-%d").strftime("%d/%m/%Y")
                punicao_min = self.db.get_total_punishment_minutes_for_day(item['Matricula'], data_db_str)
                
                values = (
                    item['Matricula'], item['Nome'], data_ptbr, 
                    item['E1'], item['S1'], item['E2'], item['S2'], 
                    item['Carga_Horaria'], format_minutes_to_hms(punicao_min), item['Total_Desconto']
                )
                
                tags = ['evenrow' if i % 2 == 0 else 'oddrow']
                if item.get('is_incomplete'): tags.append('incomplete')
                
                self.tree_viewer.insert("", "end", values=values, iid=(item['Matricula'], item['Data']), tags=tuple(tags))

            # ATUALIZA AS LABELS SUPERIORES DIRETAMENTE DO BANCO
            if target_matricula:
                info = self.db.get_funcionario_info(target_matricula)
                self.lbl_saldo_bh_total.config(text=format_minutes_to_hms(info['banco_horas']))
                self.lbl_saldo_extras_total.config(text=str(int(info['extras_disponiveis'])))
                self.lbl_fichado_status.config(text="Sim" if info['fichado'] == 1 else "Não")
                self.lbl_setor_status.config(text=info['setor'])
            else:
                self.lbl_saldo_bh_total.config(text="--:--:--")
                self.lbl_saldo_extras_total.config(text="--")

        except Exception as e:
            self.append_log(f"Erro ao carregar panorama: {e}")
    
    def on_export_panorama(self):
        """
        Gera o PDF do espelho de ponto incluindo a sugestão inteligente de saída para o sábado
        baseada no saldo atual de banco de horas.
        """
        selected_func_str = self.cmb_filter_func.get()
        start_date = self.selected_start_date
        end_date = self.selected_end_date

        if not start_date or not end_date:
            messagebox.showerror("Erro", "Selecione um período válido (Data Início e Fim).")
            return

        if not selected_func_str or selected_func_str == "Todos":
            messagebox.showerror("Erro", "Selecione um funcionário para gerar o espelho de ponto.")
            return

        target_matricula = selected_func_str.split(" - ")[0]
        nome_func = " ".join(selected_func_str.split(" - ")[1:])

        try:
            panorama_data = self.db.get_point_panorama(start_date, end_date, target_matricula)
            if not panorama_data:
                messagebox.showinfo("Aviso", "Não há dados para exportar.")
                return
            
            func_info = self.db.get_funcionario_info(target_matricula)
            is_fichado = func_info.get('fichado', 0) == 1
            saldo_bh_atual_min = func_info.get('banco_horas', 0)
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao coletar dados: {e}")
            return

        total_trabalhado_min = 0
        total_exigido_min = 0
        current_date_iter = start_date
        while current_date_iter <= end_date:
            data_str = current_date_iter.isoformat()
            if current_date_iter.weekday() != 6: # Não é domingo
                if not (is_fichado and self.db.is_holiday(data_str)):
                    total_exigido_min += MINUTOS_JORNADA_SABADO if current_date_iter.weekday() == 5 else MINUTOS_JORNADA_SEG_SEX
            current_date_iter += timedelta(days=1)
        
        for item in panorama_data:
            total_trabalhado_min += parse_hhmm_to_minutes(item.get('Carga_Horaria', '00:00:00'))

        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            title="Salvar Espelho de Ponto",
            initialfile=f"Espelho_{nome_func.replace(' ','_')}_{start_date.isoformat()}.pdf"
        )
        if not filepath: return

        try:
            doc = SimpleDocTemplate(filepath, pagesize=landscape(A4), rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.0*cm, bottomMargin=1.0*cm)
            styles = getSampleStyleSheet()
            story = []

            # Cabeçalho do Relatório
            style_title = styles['h1']
            style_title.alignment = TA_LEFT
            style_title.textColor = colors.teal
            
            if LOGO_PATH.exists():
                story.append(Image(LOGO_PATH, width=2.5*cm, height=2.5*cm, hAlign='LEFT'))
            
            story.append(Paragraph(f"Espelho de Ponto: {nome_func} (Mat. {target_matricula})", style_title))
            story.append(Paragraph(f"Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')} | Setor: {func_info.get('setor')}", styles['Normal']))
            story.append(Spacer(1, 0.5*cm))

            # Tabela de Batidas
            col_headers = ["Data", "E1", "S1", "E2", "S2", "Trabalhado", "Desconto"]
            table_data = [col_headers]
            for item in panorama_data:
                data_f = datetime.strptime(item['Data'], '%Y-%m-%d').strftime('%d/%m/%Y')
                table_data.append([data_f, item['E1'], item['S1'], item['E2'], item['S2'], item['Carga_Horaria'], item['Total_Desconto']])

            t = Table(table_data, colWidths=[3*cm, 2*cm, 2*cm, 2*cm, 2*cm, 3*cm, 3*cm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.teal),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ]))
            story.append(t)
            story.append(Spacer(1, 1*cm))

            # --- DETALHAMENTO COM SUGESTÃO DE SAÍDA ---
            story.append(Paragraph("Resumo do Saldo", styles['h2']))
            
            # Cálculo da Saída Sugerida (Sábado)
            base_date = end_date
            next_sat = self.find_next_business_day(base_date, is_fichado)
            
            if next_sat.weekday() == 5: # Se o próximo dia útil for sábado
                if saldo_bh_atual_min > 0:
                    # Pode usar até 4h (240 min) de banco de horas no sábado
                    minutos_abono = min(saldo_bh_atual_min, 240)
                    saida_padrao = datetime.combine(next_sat, time(11, 30))
                    hora_sugerida = (saida_padrao - timedelta(minutes=minutos_abono)).strftime('%H:%M')
                    msg_saida = f"{hora_sugerida} (Usa {format_minutes_to_hms(minutos_abono)} de BH)"
                else:
                    msg_saida = "11:30 (Padrão)"
            else:
                msg_saida = "N/A (Próximo dia útil não é sábado)"

            detalhes_data = [
                ["Carga Exigida no Período:", format_minutes_to_hms(total_exigido_min)],
                ["Carga Trabalhada no Período:", format_minutes_to_hms(total_trabalhado_min)],
                ["Saldo Atual Banco de Horas:", format_minutes_to_hms(saldo_bh_atual_min)],
                ["Sugestão de Saída (Próximo Sábado):", msg_saida]
            ]

            t_det = Table(detalhes_data, colWidths=[8*cm, 6*cm])
            t_det.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
                ('BACKGROUND', (0,3), (1,3), colors.navajowhite), # Destaque na sugestão
            ]))
            story.append(t_det)

            doc.build(story)
            messagebox.showinfo("Sucesso", f"Relatório exportado com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro PDF", f"Erro ao gerar relatório: {e}")

    def append_log(self, text):
            if hasattr(self, 'log_area'):
                self.log_area.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {text}\n");
                self.log_area.see(tk.END)
            else:
                print(text)
                
    def start_in_place_edit(self, event):
        if self.editing_widgets: 
            [w.destroy() for w in self.editing_widgets.values()]
            self.editing_widgets.clear()
            
        item_id = self.tree_viewer.identify_row(event.y)
        if not item_id: return
        
        column_id = self.tree_viewer.identify_column(event.x)
        try: 
            col_index = int(column_id.replace('#', '')) - 1 
            column_name = self.tree_viewer.heading(column_id, 'text')
        except: return

        editable_columns = ["E1", "S1", "E2", "S2", "Total Desconto"]
        if column_name not in editable_columns: return

        x, y, width, height = self.tree_viewer.bbox(item_id, column_id)
        values = self.tree_viewer.item(item_id, 'values')
        matricula, data_ptbr = values[0], values[2]
        current_val = values[col_index]
        data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")

        if data_db < SYSTEM_START_DATE:
            self.append_log(f"Edição bloqueada: Data anterior ao sistema.")
            return

        entry_edit = ttk.Entry(self.tree_viewer)
        entry_edit.place(x=x, y=y, width=width, height=height)
        entry_edit.insert(0, current_val if current_val not in ('', 'N/A') else '')
        entry_edit.focus()

        justificativa_cmb = ttk.Combobox(self.tree_viewer, values=LISTA_JUSTIFICATIVAS, state="readonly", width=30)
        justificativa_cmb.place(x=x + width + 5, y=y, height=height)
        
        edit_key = (matricula, data_db)
        justificativa_cmb.set(self.unsaved_edits.get(edit_key, {}).get('justificativa', LISTA_JUSTIFICATIVAS[0]))
        
        self.editing_widgets = {'entry': entry_edit, 'cmb': justificativa_cmb}

        def on_escape(e=None):
            if self.editing_widgets: 
                [w.destroy() for w in self.editing_widgets.values()]
                self.editing_widgets.clear()

        def handle_edit(event=None):
            if not self.editing_widgets: return
            entry = self.editing_widgets.get('entry')
            cmb = self.editing_widgets.get('cmb')
            
            new_value = entry.get().strip()
            just = cmb.get()

            # Validação de Formato
            if column_name == "Total Desconto":
                if not re.match(r'^-?\d{1,4}:\d{2}(:\d{2})?$', new_value):
                    messagebox.showerror("Erro", "Use o formato HH:MM")
                    return
            else:
                if not (re.match(r'^\d{2}:\d{2}$', new_value) or new_value in ('', 'N/A', '00:00')):
                    messagebox.showerror("Erro", "Use o formato HH:MM")
                    return

            # --- PENTE FINO: RESET DE PENALIDADE MANUAL ---
            # Se você mexer no horário, o sistema OBRIGATORIAMENTE deleta a punição manual anterior
            if column_name in ["E1", "S1", "E2", "S2"] and edit_key in self.unsaved_edits:
                if 'Total_Desconto' in self.unsaved_edits[edit_key]:
                    del self.unsaved_edits[edit_key]['Total_Desconto']
                    self.append_log(f"Horário alterado: Recalculando punição automática para {data_ptbr}.")

            # Atualiza a visualização da Treeview
            temp_vals = list(self.tree_viewer.item(item_id, 'values'))
            temp_vals[col_index] = new_value
            self.tree_viewer.item(item_id, values=tuple(temp_vals))

            if edit_key not in self.unsaved_edits:
                self.unsaved_edits[edit_key] = {
                    'E1': temp_vals[3], 'S1': temp_vals[4], 
                    'E2': temp_vals[5], 'S2': temp_vals[6],
                    'Total_Desconto': temp_vals[9]
                }
            
            key_map = {"E1":"E1", "S1":"S1", "E2":"E2", "S2":"S2", "Total Desconto":"Total_Desconto"}
            self.unsaved_edits[edit_key][key_map[column_name]] = new_value
            self.unsaved_edits[edit_key]['justificativa'] = just
            
            # Força o recálculo visual passando qual coluna foi mexida
            self.update_visual_work_hours(item_id, edited_column=column_name)
            on_escape()

        def on_escape(e=None):
            if self.editing_widgets: 
                [w.destroy() for w in self.editing_widgets.values()]
                self.editing_widgets.clear()

        def handle_edit(event=None):
            if not self.editing_widgets: return
            entry = self.editing_widgets.get('entry')
            cmb = self.editing_widgets.get('cmb')
            
            new_value = entry.get().strip()
            just = cmb.get()

            if column_name == "Total Desconto":
                if not re.match(r'^-?\d{1,4}:\d{2}(:\d{2})?$', new_value):
                    messagebox.showerror("Erro", "Use o formato HH:MM (ex: 00:15 ou -00:10)")
                    return
            else:
                if not (re.match(r'^\d{2}:\d{2}$', new_value) or new_value in ('', 'N/A', '00:00')):
                    messagebox.showerror("Erro", "Use o formato HH:MM")
                    return

            temp_vals = list(self.tree_viewer.item(item_id, 'values'))
            temp_vals[col_index] = new_value
            self.tree_viewer.item(item_id, values=tuple(temp_vals))

            if edit_key not in self.unsaved_edits:
                self.unsaved_edits[edit_key] = {
                    'E1': temp_vals[3], 'S1': temp_vals[4], 
                    'E2': temp_vals[5], 'S2': temp_vals[6],
                    'Total_Desconto': temp_vals[9]
                }
            
            key_map = {"E1":"E1", "S1":"S1", "E2":"E2", "S2":"S2", "Total Desconto":"Total_Desconto"}
            self.unsaved_edits[edit_key][key_map[column_name]] = new_value
            self.unsaved_edits[edit_key]['justificativa'] = just
            
            # Passamos o column_name para a função saber se deve avisar sobre o abono
            self.update_visual_work_hours(item_id, edited_column=column_name)
            on_escape()

        entry_edit.bind("<Return>", handle_edit)
        entry_edit.bind("<Escape>", on_escape)
        justificativa_cmb.bind("<<ComboboxSelected>>", lambda e: entry_edit.focus())

        def on_escape(e=None):
            if self.editing_widgets: 
                [w.destroy() for w in self.editing_widgets.values()]
                self.editing_widgets.clear()

        def handle_edit(event=None): # Agora aceita o evento do teclado
            if not self.editing_widgets: return
            entry = self.editing_widgets.get('entry')
            cmb = self.editing_widgets.get('cmb')
            
            new_value = entry.get().strip()
            just = cmb.get()

            # Validação
            if column_name == "Total Desconto":
                if not re.match(r'^-?\d{1,4}:\d{2}(:\d{2})?$', new_value):
                    messagebox.showerror("Erro", "Use o formato HH:MM (ex: 00:15 ou -00:10)")
                    return
            else:
                if not (re.match(r'^\d{2}:\d{2}$', new_value) or new_value in ('', 'N/A', '00:00')):
                    messagebox.showerror("Erro", "Use o formato HH:MM")
                    return

            # Atualiza visualmente a Treeview
            temp_vals = list(self.tree_viewer.item(item_id, 'values'))
            temp_vals[col_index] = new_value
            self.tree_viewer.item(item_id, values=tuple(temp_vals))

            # Salva no dicionário de alterações pendentes
            if edit_key not in self.unsaved_edits:
                self.unsaved_edits[edit_key] = {
                    'E1': temp_vals[3], 'S1': temp_vals[4], 
                    'E2': temp_vals[5], 'S2': temp_vals[6],
                    'Total_Desconto': temp_vals[9]
                }
            
            # Mapeia o nome da coluna para a chave correta no dicionário
            key_map = {"E1":"E1", "S1":"S1", "E2":"E2", "S2":"S2", "Total Desconto":"Total_Desconto"}
            self.unsaved_edits[edit_key][key_map[column_name]] = new_value
            self.unsaved_edits[edit_key]['justificativa'] = just
            
            self.update_visual_work_hours(item_id)
            on_escape()

        # BINDINGS PARA ENTER E ESC
        entry_edit.bind("<Return>", handle_edit)
        entry_edit.bind("<Escape>", on_escape)
        justificativa_cmb.bind("<<ComboboxSelected>>", lambda e: entry_edit.focus())

    def update_visual_work_hours(self, item_id, edited_column=None):
        """
        Atualiza instantaneamente a Carga Horária e o Desconto na tabela visual (Treeview)
        quando o usuário altera um horário de batida.
        """
        values = self.tree_viewer.item(item_id, 'values')
        matricula, data_ptbr = values[0], values[2]
        data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        all_times_raw = [values[3], values[4], values[5], values[6]]
        
        func_info = self.db.get_funcionario_info(matricula)
        sector = func_info.get('setor', 'N/D')
        edit_key = (matricula, data_db)

        # 1. Soma de atraso acumulado real baseado no que está na tela
        total_late_min = 0
        total_worked_raw = 0
        for i in range(0, 4, 2):
            e_time, s_time = all_times_raw[i], all_times_raw[i+1]
            if e_time and e_time not in ('N/A', '00:00', ''):
                try:
                    ent = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M")
                    oficial = '07:30' if i < 2 else '13:00'
                    j_ini = datetime.strptime(f"{data_db} {oficial}", "%Y-%m-%d %H:%M")
                    total_late_min += max(0, (ent - j_ini).total_seconds() / 60)

                    if s_time and s_time not in ('N/A', '00:00', ''):
                        sai = datetime.strptime(f"{data_db} {s_time}", "%Y-%m-%d %H:%M")
                        if sai < ent: sai += timedelta(days=1)
                        total_worked_raw += (sai - ent).total_seconds() / 60
                except: continue

        # 2. Decisão da Penalidade Visual
        # Se a última coluna editada foi 'Total Desconto', mantemos o valor manual.
        # Se foi qualquer horário (E1, S1, etc.), recalculamos automaticamente.
        if edited_column == "Total Desconto" and edit_key in self.unsaved_edits:
            penalidade_final = parse_hhmm_to_minutes(self.unsaved_edits[edit_key]['Total_Desconto'])
        else:
            # Se você botou 07:30 na tela, aqui resultará em 00:00:00
            penalidade_final = calculate_deduction(total_late_min, sector)

        # 3. Atualiza os campos na Treeview
        new_values = list(values)
        new_values[7] = format_minutes_to_hms(max(0, total_worked_raw - penalidade_final)) # Carga Líquida
        new_values[9] = format_minutes_to_hms(penalidade_final) # Total Desconto
        
        self.tree_viewer.item(item_id, values=tuple(new_values))


    def process_manual_update_and_save(self, matricula, data_db, all_times_raw, justificativa, desconto_manual=None):
        """
        Processa ajuste manual de batidas, salva o dia e recalcula o saldo total do funcionário.

        Regras:
        - recalcula corretamente E1/S1/E2/S2;
        - aplica multiplicador de atraso por setor;
        - aceita desconto manual, que prevalece quando informado;
        - grava horas_trabalhadas;
        - reprocessa o saldo total e persiste em funcionarios.
        """
        try:
            matricula = str(matricula).split(" - ")[0].strip()
            func_info = self.db.get_funcionario_info(matricula)
            if not func_info:
                raise Exception(f"Funcionário não encontrado: {matricula}")

            setor = func_info.get("setor", "N/D")

            tempos = list(all_times_raw) if all_times_raw else []
            while len(tempos) < 4:
                tempos.append("")

            tempos = [(t or "").strip() for t in tempos]
            tempos_normalizados = []
            for t in tempos:
                if t in ("N/A", "00:00", ""):
                    tempos_normalizados.append("")
                else:
                    tempos_normalizados.append(t)

            periodos = []
            minutos_totais_brutos = 0.0
            minutos_totais_deducao = 0.0

            pares = [
                ("07:30", tempos_normalizados[0], tempos_normalizados[1], 0),
                ("13:00", tempos_normalizados[2], tempos_normalizados[3], 2),
            ]

            for horario_oficial, entrada_raw, saida_raw, turno_idx in pares:
                if not entrada_raw:
                    continue

                try:
                    entrada = datetime.strptime(f"{data_db} {entrada_raw}", "%Y-%m-%d %H:%M")
                except ValueError:
                    continue

                saida = None
                if saida_raw:
                    try:
                        saida = datetime.strptime(f"{data_db} {saida_raw}", "%Y-%m-%d %H:%M")
                        if saida < entrada:
                            saida += timedelta(days=1)
                    except ValueError:
                        saida = None

                deducao_periodo = 0.0
                minutos_brutos = 0.0
                minutos_liquidos = 0.0

                jornada_inicio = datetime.strptime(f"{data_db} {horario_oficial}", "%Y-%m-%d %H:%M")
                atraso_minutos = max(0, (entrada - jornada_inicio).total_seconds() / 60)

                if saida:
                    minutos_brutos = max(0, (saida - entrada).total_seconds() / 60)
                    deducao_periodo = calculate_deduction(atraso_minutos, setor)
                    minutos_liquidos = max(0, minutos_brutos - deducao_periodo)
                else:
                    minutos_brutos = 0.0
                    deducao_periodo = calculate_deduction(atraso_minutos, setor)
                    minutos_liquidos = 0.0

                minutos_totais_brutos += minutos_brutos
                minutos_totais_deducao += deducao_periodo

                periodos.append({
                    "entrada": entrada.strftime("%Y-%m-%d %H:%M:%S") if entrada else None,
                    "saida": saida.strftime("%Y-%m-%d %H:%M:%S") if saida else None,
                    "minutos_brutos": format_minutes_to_hms(minutos_brutos),
                    "deducao_minutos": format_minutes_to_hms(deducao_periodo),
                    "minutos_liquidos": format_minutes_to_hms(minutos_liquidos)
                })

            desconto_manual_min = parse_hhmm_to_minutes(desconto_manual) if desconto_manual else 0

            if desconto_manual_min > 0 and periodos:
                desconto_automatico_total = sum(parse_hhmm_to_minutes(p["deducao_minutos"]) for p in periodos)
                diferenca = desconto_manual_min - desconto_automatico_total

                primeira_deducao = parse_hhmm_to_minutes(periodos[0]["deducao_minutos"])
                nova_primeira_deducao = max(0, primeira_deducao + diferenca)
                periodos[0]["deducao_minutos"] = format_minutes_to_hms(nova_primeira_deducao)

                minutos_totais_deducao = 0.0
                for p in periodos:
                    minutos_brutos_p = parse_hhmm_to_minutes(p["minutos_brutos"])
                    minutos_deducao_p = parse_hhmm_to_minutes(p["deducao_minutos"])
                    minutos_liquidos_p = max(0, minutos_brutos_p - minutos_deducao_p)

                    p["minutos_liquidos"] = format_minutes_to_hms(minutos_liquidos_p)
                    minutos_totais_deducao += minutos_deducao_p

            minutos_totais_liquidos = 0.0
            for p in periodos:
                minutos_totais_liquidos += parse_hhmm_to_minutes(p["minutos_liquidos"])

            self.db.insert_horas_trabalhadas({
                "matricula": matricula,
                "data": data_db,
                "minutos_totais": format_minutes_to_hms(minutos_totais_liquidos),
                "periodos": periodos
            }, justificativa=justificativa)

            recalc_ok = self.db.recalculate_full_balance_for_employee(matricula)
            if not recalc_ok:
                raise Exception(f"Falha ao recalcular saldo do funcionário {matricula}")

            info_atualizada = self.db.get_funcionario_info(matricula)

            self.append_log(
                f"Ajuste salvo para {matricula} em {data_db} | "
                f"Bruto: {format_minutes_to_hms(minutos_totais_brutos)} | "
                f"Desconto: {format_minutes_to_hms(minutos_totais_deducao)} | "
                f"Líquido: {format_minutes_to_hms(minutos_totais_liquidos)} | "
                f"BH Atual: {format_minutes_to_hms(info_atualizada.get('banco_horas', 0) or 0)} | "
                f"Extras: {int(info_atualizada.get('extras_disponiveis', 0) or 0)}"
            )

            return True

        except Exception as e:
            self.append_log(f"ERRO ao salvar ajuste manual de {matricula} em {data_db}: {e}")
            return False


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
                self.process_manual_update_and_save(
                    matricula, 
                    data_db, 
                    [edits.get('E1',''), edits.get('S1',''), edits.get('E2',''), edits.get('S2','')], 
                    justificativa,
                    desconto_manual=edits.get('Total_Desconto') # Passa o desconto editado
                )

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
                self.load_point_viewer(force_reload=True)
                self._update_calendar_tags()


    # --- Ponto de Entrada Principal ---
    def check_for_updates(self):
            """Inicia a verificação de atualização em uma thread separada para não travar a UI."""
            self.append_log("Verificando atualizações...")
            # Desabilita o botão para evitar cliques duplos (opcional, mas recomendado)
            # (Você precisaria guardar uma referência ao botão para fazer isso)
            
            # Inicia a verificação em background
            threading.Thread(target=self._run_update_check, daemon=True).start()

    def _run_update_check(self):
        """Executa a lógica de verificação e download da atualização."""
        # Aponta para o novo repositório PÚBLICO de lançamentos
        API_URL = "https://api.github.com/repos/SH1NNxs/projeto_ponto-releases/releases/latest"
        
        try:
            response = requests.get(API_URL, headers={"Accept": "application/vnd.github.v3+json"}, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            latest_tag = data.get('tag_name')
            
            if not latest_tag:
                self.append_log("Não foi possível encontrar a tag da última versão.")
                messagebox.showerror("Erro de Atualização", "Não foi possível ler a tag da última versão no GitHub.", parent=self.root)
                return

            self.append_log(f"Versão atual: {CURRENT_VERSION}. Versão mais recente: {latest_tag}")

            # Compara as versões
            if version.parse(latest_tag) > version.parse(CURRENT_VERSION):
                self.append_log(f"Nova versão {latest_tag} encontrada!")
                
                # --- LÓGICA DE DOWNLOAD AUTOMÁTICO ---
                
                # 1. Encontrar a URL do asset (.exe)
                asset_url = None
                exe_name = None
                for asset in data.get('assets', []):
                    # Procura pelo nome do .exe principal (sem espaços)
                    if asset.get('name', '').lower() == "WN-Ponto-Certo.exe".lower():
                        asset_url = asset.get('browser_download_url')
                        exe_name = asset.get('name')
                        break
                
                if not asset_url:
                    self.append_log("Erro: Lançamento encontrado, mas sem 'WN Ponto Certo.exe' anexado.")
                    messagebox.showerror("Erro de Atualização", "A nova versão foi encontrada, mas não há um ficheiro .exe para baixar.", parent=self.root)
                    return

                if not messagebox.askyesno("Nova Versão Encontrada",
                                       f"Uma nova versão ({latest_tag}) está disponível!\n\n"
                                       "Deseja baixar e instalar a atualização agora?\n\n"
                                       "O programa será reiniciado.",
                                       parent=self.root):
                    self.append_log("Atualização recusada pelo usuário.")
                    return

                # 2. Baixar o .exe para um ficheiro temporário
                self.append_log(f"A baixar {exe_name}...")
                
                temp_dir = tempfile.gettempdir()
                new_exe_temp_path = os.path.join(temp_dir, f"{exe_name}_new.exe")

                with requests.get(asset_url, stream=True) as r:
                    r.raise_for_status()
                    with open(new_exe_temp_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                
                self.append_log(f"Download concluído: {new_exe_temp_path}")

                # 3. Localizar o updater.exe e o .exe atual
                # (sys.executable é o caminho para o .exe atual quando compilado)
                current_exe_path = sys.executable
                current_dir = os.path.dirname(current_exe_path)
                updater_exe_path = os.path.join(current_dir, "updater.exe")

                if not os.path.exists(updater_exe_path):
                    self.append_log("ERRO CRÍTICO: updater.exe não encontrado!")
                    messagebox.showerror("Erro de Atualização", f"O ficheiro 'updater.exe' não foi encontrado na pasta do programa.\n\nA atualização não pode continuar.", parent=self.root)
                    return

                # 4. Chamar o updater e fechar
                self.append_log("A iniciar o updater e a fechar...")

                pid = os.getpid()
                
                subprocess.Popen([updater_exe_path, str(pid), current_exe_path, new_exe_temp_path])
                
                # Fecha o programa principal
                self.root.destroy()
                
                # --- FIM DA LÓGICA DE DOWNLOAD ---

            else:
                self.append_log("O sistema já está atualizado.")
                messagebox.showinfo("Tudo Certo!",
                                    f"Você já está com a versão mais recente ({CURRENT_VERSION}).",
                                    parent=self.root)

        except requests.exceptions.Timeout:
            self.append_log("Erro: A verificação de atualização demorou demais (timeout).")
            messagebox.showwarning("Erro de Rede", "Não foi possível verificar atualizações.\nVerifique sua conexão com a internet.", parent=self.root)
        except requests.exceptions.RequestException as e:
            self.append_log(f"Erro ao verificar atualização: {e}")
            messagebox.showerror("Erro de Atualização", f"Não foi possível se conectar ao GitHub para verificar atualizações.\n\nDetalhe: {e}", parent=self.root)
        except Exception as e:
            self.append_log(f"Erro inesperado na verificação: {e}")
            messagebox.showerror("Erro", f"Ocorreu um erro inesperado: {e}", parent=self.root)
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()