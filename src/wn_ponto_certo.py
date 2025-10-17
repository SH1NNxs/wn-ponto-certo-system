import os
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
from collections import defaultdict
from datetime import datetime, timedelta, date
import sqlite3
import json
from pathlib import Path
from tkcalendar import Calendar
import re

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
DEFAULT_DB = Path(__file__).parent.joinpath("ponto.db")
LOGO_PATH = Path(__file__).parent.joinpath("wn_logo.png")

# -------------------------
# CONSTANTES E FUNÇÕES DE APOIO
# -------------------------
MINUTOS_JORNADA_SEG_SEX = 8 * 60
MINUTOS_JORNADA_SABADO = 4 * 60
MINUTOS_UNIDADE_EXTRA = 4 * 60

LISTA_JUSTIFICATIVAS = ["Ajuste Manual (Erro Batida)", "Início Externo", "Atestado Médico", "Saída Justificada", "Esquecimento Batida"]
LISTA_SETORES = ["Produtivo", "Administrativo", "N/D"]
LISTA_FICHADO = ["Sim", "Não"]
LISTA_TIPO_FERIADO = ["Nacional", "Estadual", "Municipal", "Ponto Facultativo"]

def try_parse_datetime(s, format_to_try="%Y-%m-%d %H:%M:%S"):
    try: return datetime.strptime(s, format_to_try)
    except:
        try: return datetime.strptime(s, "%Y/%m/%d %H:%M:%S")
        except:
            try: return datetime.strptime(s, "%Y/%m/%d %H:%M")
            except: return None

def calculate_deduction(minutes_late, sector=None):
    minutes_late = max(0, minutes_late)
    if minutes_late <= 5: return 0
    elif minutes_late <= 15:
        multiplier = 2 if sector == "Administrativo" else 3
        return minutes_late * multiplier
    elif minutes_late <= 30:
        multiplier_faixa2 = 2 if sector == "Administrativo" else 3
        p1 = 15 * multiplier_faixa2
        p2 = (minutes_late - 15) * 2
        return p1 + p2
    else:
        multiplier_faixa2 = 2 if sector == "Administrativo" else 3
        p1 = 15 * multiplier_faixa2
        p2 = (30 - 15) * 2
        p3 = (minutes_late - 30) * 1
        return p1 + p2 + p3

def format_minutes_to_hms(minutes):
    if minutes is None: return "00:00:00"
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    hours = int(minutes // 60)
    remaining_minutes = int(minutes % 60)
    seconds = round((minutes * 60) % 60)
    if seconds == 60:
        remaining_minutes += 1
        seconds = 0
    if remaining_minutes == 60:
        hours += 1
        remaining_minutes = 0
    return f"{sign}{hours:02}:{remaining_minutes:02}:{seconds:02}"

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
        c.execute("CREATE TABLE IF NOT EXISTS funcionarios (id INTEGER PRIMARY KEY, matricula TEXT UNIQUE, nome TEXT, salario REAL DEFAULT 0, banco_horas REAL DEFAULT 0, extras_disponiveis INTEGER DEFAULT 0, fichado INTEGER DEFAULT 0, setor TEXT DEFAULT 'N/D')")
        c.execute("CREATE TABLE IF NOT EXISTS horas_trabalhadas (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, minutos_totais TEXT, periodos TEXT, criado_em DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        c.execute("CREATE TABLE IF NOT EXISTS log_edicoes (id INTEGER PRIMARY KEY, matricula TEXT, data_ponto TEXT, data_edicao DATETIME DEFAULT CURRENT_TIMESTAMP, periodos_antigos TEXT, periodos_novos TEXT, justificativa TEXT, usuario TEXT DEFAULT 'SYSTEM/MANUAL')")
        c.execute("CREATE TABLE IF NOT EXISTS feriados (id INTEGER PRIMARY KEY, data TEXT UNIQUE, descricao TEXT, tipo TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS punicoes (id INTEGER PRIMARY KEY, matricula TEXT, data_punicao TEXT, minutos_descontados REAL DEFAULT 0, motivo TEXT, data_registro DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (matricula) REFERENCES funcionarios (matricula))")
        self.conn.commit()

    def populate_fixed_holidays(self):
        ano_atual = str(datetime.now().year)
        fixed_holidays = [(f'{ano_atual}-01-01','Confraternização Universal','Nacional'),(f'{ano_atual}-03-06','Data Magna PE','Estadual'),(f'{ano_atual}-04-21','Tiradentes','Nacional'),(f'{ano_atual}-05-01','Dia Trabalhador','Nacional'),(f'{ano_atual}-06-24','São João','Estadual'),(f'{ano_atual}-09-07','Independência BR','Nacional'),(f'{ano_atual}-10-12','N Sra Aparecida','Nacional'),(f'{ano_atual}-11-02','Finados','Nacional'),(f'{ano_atual}-11-15','Proclamação República','Nacional'),(f'{ano_atual}-12-25','Natal','Nacional')]
        try:
            c = self.conn.cursor()
            [c.execute("INSERT OR IGNORE INTO feriados (data, descricao, tipo) VALUES (?, ?, ?)", h) for h in fixed_holidays]
            self.conn.commit()
        except Exception as e:
            print(f"Erro feriados: {e}")

    def add_holiday(self, data_str, descricao, tipo):
        try:
            self.conn.execute("INSERT OR REPLACE INTO feriados (data, descricao, tipo) VALUES (?, ?, ?)", (data_str, descricao, tipo))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Erro add feriado: {e}")
            return False

    def get_holidays_for_month(self, year, month):
        c = self.conn.cursor()
        query = "SELECT data FROM feriados WHERE strftime('%Y-%m', data) = ?"
        target_month = f"{year:04}-{month:02}"
        c.execute(query, (target_month,))
        holiday_dates = set()
        [holiday_dates.add(datetime.strptime(row['data'], '%Y-%m-%d').date()) for row in c.fetchall() if row['data']]
        return holiday_dates

    def get_holidays_in_range(self, start_date, end_date):
        c = self.conn.cursor()
        start_date_str = start_date.isoformat() if isinstance(start_date, date) else start_date
        end_date_str = end_date.isoformat() if isinstance(end_date, date) else end_date
        query = "SELECT data, descricao, tipo FROM feriados WHERE data BETWEEN ? AND ? ORDER BY data"
        c.execute(query, (start_date_str, end_date_str))
        return [dict(row) for row in c.fetchall()]

    def add_punicao(self, matricula, data_punicao_str, minutos_descontados, motivo):
        try:
            with self.conn:
                self.conn.execute("INSERT INTO punicoes (matricula, data_punicao, minutos_descontados, motivo) VALUES (?, ?, ?, ?)", (matricula, data_punicao_str, minutos_descontados, motivo))
                self.conn.execute("UPDATE funcionarios SET banco_horas = banco_horas - ? WHERE matricula = ?", (minutos_descontados, matricula))
                info_apos = self.get_funcionario_info(matricula)
                periodo_antigo = f"Punição: 0 min (BH antes: {format_minutes_to_hms(info_apos.get('banco_horas', 0) + minutos_descontados)})"
                periodo_novo = f"Punição: {format_minutes_to_hms(minutos_descontados)} (BH depois: {format_minutes_to_hms(info_apos.get('banco_horas', 0))})"
                self.log_edicao(matricula, data_punicao_str, periodo_antigo, periodo_novo, f"Punição: {motivo}")
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
        query = "SELECT data_punicao, minutos_descontados, motivo FROM punicoes WHERE matricula = ? AND data_punicao BETWEEN ? AND ? ORDER BY data_punicao"
        c.execute(query, (matricula, start_date_str, end_date_str))
        return [dict(row) for row in c.fetchall()]

    def is_holiday(self, data_str):
        try:
            c = self.conn.cursor()
            c.execute("SELECT 1 FROM feriados WHERE data = ?", (data_str,))
            return c.fetchone() is not None
        except:
            return False

    def get_expected_daily_minutes(self, date_str, is_fichado):
        is_holiday_today = self.is_holiday(date_str)
        if is_holiday_today:
            if is_fichado:
                return 0
        try:
            date_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            if date_dt.weekday() < 5: return MINUTOS_JORNADA_SEG_SEX
            elif date_dt.weekday() == 5: return MINUTOS_JORNADA_SABADO
            else: return 0
        except ValueError:
            return 0

    def insert_funcionario(self, dados):
        self.conn.execute("INSERT OR IGNORE INTO funcionarios (matricula, nome, fichado, setor) VALUES (?, ?, ?, ?)", (dados.get("matricula"), dados.get("nome"), dados.get("fichado", 0), dados.get("setor", "N/D")))
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
        query = "SELECT l.data_ponto, l.data_edicao, l.periodos_antigos, l.periodos_novos, l.justificativa, f.nome FROM log_edicoes l JOIN funcionarios f ON l.matricula = f.matricula WHERE l.matricula = ? AND l.data_ponto BETWEEN ? AND ? ORDER BY l.data_ponto, l.data_edicao"
        c.execute(query, (matricula, start_date_str, end_date_str))
        return [dict(row) for row in c.fetchall()]

    def _get_daily_summary_for_display(self, matricula, data_str):
        c = self.conn.cursor()
        c.execute("SELECT minutos_totais, periodos FROM horas_trabalhadas WHERE matricula=? AND data=?", (matricula, data_str))
        row = c.fetchone()
        if not row: return "00:00:00", "00:00:00"
        total_worked, total_delay_minutes = row['minutos_totais'], 0
        try:
            for p in json.loads(row['periodos']):
                h, m, s = map(int, p['deducao_minutos'].split(':'))
                total_delay_minutes += h * 60 + m + s / 60
        except: pass
        return total_worked, format_minutes_to_hms(total_delay_minutes)

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
        sql_todos_horas = f"SELECT matricula, data, periodos, minutos_totais FROM horas_trabalhadas WHERE matricula IN ({placeholders}) ORDER BY data ASC"
        c.execute(sql_todos_horas, matriculas_list)
        todos_os_dados_historicos = c.fetchall()
        panorama_final = []
        for func_base in funcionarios:
            if not func_base: continue
            matricula = func_base['matricula']
            info_final_real = self.get_funcionario_info(matricula)
            is_fichado = info_final_real.get('fichado', 0) == 1
            saldo_bh_real_final = info_final_real.get('banco_horas', 0)
            saldo_extras_real_final = info_final_real.get('extras_disponiveis', 0)
            saldo_bh_simulado, saldo_extras_simulado = 0, 0
            historico_simulado = {}
            dados_func = [r for r in todos_os_dados_historicos if r['matricula'] == matricula]
            for row in dados_func:
                bh_anterior_simulado = saldo_bh_simulado
                extras_anterior_simulado = saldo_extras_simulado
                excedente_dia = 0
                try:
                    minutos_trabalhados = 0
                    if row['minutos_totais'] and ':' in row['minutos_totais']:
                        h, m, s = map(int, row['minutos_totais'].split(':'))
                        minutos_trabalhados = h * 60 + m + s / 60
                    excedente_dia = minutos_trabalhados - self.get_expected_daily_minutes(row['data'], is_fichado)
                    saldo_bh_simulado += excedente_dia
                    while saldo_bh_simulado >= MINUTOS_UNIDADE_EXTRA:
                        saldo_bh_simulado -= MINUTOS_UNIDADE_EXTRA
                        saldo_extras_simulado += 1
                    while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                        saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                        saldo_extras_simulado -= 1
                except: continue
                historico_simulado[row['data']] = {'bh_anterior': bh_anterior_simulado, 'bh_saldo': saldo_bh_simulado, 'extras_anterior': extras_anterior_simulado, 'extras_saldo': saldo_extras_simulado}
            bh_diff = saldo_bh_real_final - saldo_bh_simulado
            extras_diff = saldo_extras_real_final - saldo_extras_simulado
            current_date_iter = start_dt
            while current_date_iter <= end_dt:
                data_str = current_date_iter.isoformat()
                dados_do_dia = next((r for r in dados_func if r['data'] == data_str), None)
                simulacao_do_dia = historico_simulado.get(data_str)
                if not simulacao_do_dia:
                    last_sim_date = max((d for d in historico_simulado if d < data_str), default=None)
                    if last_sim_date:
                        simulacao_do_dia = {'bh_anterior': historico_simulado[last_sim_date]['bh_saldo'], 'bh_saldo': historico_simulado[last_sim_date]['bh_saldo'],'extras_anterior': historico_simulado[last_sim_date]['extras_saldo'], 'extras_saldo': historico_simulado[last_sim_date]['extras_saldo']}
                    else:
                        simulacao_do_dia = {'bh_anterior': 0, 'bh_saldo': 0, 'extras_anterior': 0, 'extras_saldo': 0}
                carga_horaria_dia_str, total_desconto, horarios = "00:00:00", "00:00:00", []
                if dados_do_dia:
                    carga_horaria_dia_str = dados_do_dia['minutos_totais']
                    total_desconto = self._get_daily_summary_for_display(matricula, data_str)[1]
                    try:
                        for p in json.loads(dados_do_dia['periodos']):
                            horarios.extend([datetime.strptime(p['entrada'], '%Y-%m-%d %H:%M:%S').strftime('%H:%M'), datetime.strptime(p['saida'], '%Y-%m-%d %H:%M:%S').strftime('%H:%M')])
                    except: pass
                ponto_dict = {'Matricula': matricula, 'Nome': info_final_real['nome'], 'Data': data_str, 'E1': '', 'S1': '', 'E2': '', 'S2': '', 'Carga_Horaria': carga_horaria_dia_str, 'Total_Desconto': total_desconto, 'BH_Anterior': format_minutes_to_hms(simulacao_do_dia['bh_anterior'] + bh_diff), 'BH_Saldo': format_minutes_to_hms(simulacao_do_dia['bh_saldo'] + bh_diff), 'Extras_Disp': str(int(simulacao_do_dia['extras_saldo'] + extras_diff))}
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
              AND minutos_totais IS NOT NULL 
              AND minutos_totais != '00:00:00'
            ORDER BY data
        """
        c.execute(query, (matricula, start_date_str, end_date_str))
        
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
            self.conn.execute("UPDATE funcionarios SET banco_horas = banco_horas - ?, extras_disponiveis = extras_disponiveis - ? WHERE matricula = ?", (minutos_a_deduzir_bh, unidades_a_deduzir_extras, matricula))
            self.conn.commit()
            data_hoje = datetime.now().strftime("%Y-%m-%d")
            justificativa = "Pagamento/Dedução Saldo"
            periodo_antigo = f"BH: {format_minutes_to_hms(saldo_bh_antes)}, Extras: {int(saldo_extras_antes)}"
            periodo_novo = f"BH: {format_minutes_to_hms(saldo_bh_antes - minutos_a_deduzir_bh)}, Extras: {int(saldo_extras_antes - unidades_a_deduzir_extras)}"
            self.log_edicao(matricula, data_hoje, periodo_antigo, periodo_novo, justificativa)
            return True
        except Exception as e:
            print(f"Erro update saldos: {e}")
            return False

    def recalculate_full_balance_for_employee(self, matricula):
        c = self.conn.cursor()
        func_info = self.get_funcionario_info(matricula)
        is_fichado = func_info.get('fichado', 0) == 1
        c.execute("SELECT data, minutos_totais FROM horas_trabalhadas WHERE matricula = ? ORDER BY data ASC", (matricula,))
        all_work_days = c.fetchall()
        saldo_bh_minutos, saldo_extras = 0, 0
        for day in all_work_days:
            excedente_dia = 0
            try:
                minutos_trabalhados = 0
                if day['minutos_totais'] and ':' in day['minutos_totais']:
                    h, m, s = map(int, day['minutos_totais'].split(':'))
                    minutos_trabalhados = h * 60 + m + s / 60
                excedente_dia = minutos_trabalhados - self.get_expected_daily_minutes(day['data'], is_fichado)
                saldo_bh_minutos += excedente_dia
                while saldo_bh_minutos >= MINUTOS_UNIDADE_EXTRA:
                    saldo_bh_minutos -= MINUTOS_UNIDADE_EXTRA
                    saldo_extras += 1
                while saldo_bh_minutos < 0 and saldo_extras > 0:
                    saldo_bh_minutos += MINUTOS_UNIDADE_EXTRA
                    saldo_extras -= 1
            except Exception as e:
                print(f"Erro ao calcular excedente dia {day['data']} para {matricula}: {e}")
                continue
        c.execute("SELECT SUM(minutos_descontados) as total_punicao FROM punicoes WHERE matricula = ?", (matricula,))
        punicao_total = c.fetchone()['total_punicao'] or 0
        saldo_bh_minutos -= punicao_total
        self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (saldo_bh_minutos, saldo_extras, matricula))
        self.conn.commit()


def import_glog_txt(filepath, db_manager, logger=print):
    employees_points_raw = defaultdict(lambda: defaultdict(list))
    unique_employees = set()
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f.readlines()[1:]:
                parts = re.split(r'\s+', line.strip())
                if len(parts) < 8: continue
                try:
                    matricula, nome = str(parts[2]).zfill(8), str(parts[3]).strip()
                    dt = try_parse_datetime(f"{parts[6]} {parts[7]}")
                    if dt:
                        unique_employees.add((matricula, nome))
                        employees_points_raw[matricula][dt.date().isoformat()].append({"datetime": dt})
                except: continue
    except Exception as e:
        logger(f"ERRO LEITURA ARQUIVO: {e}")
        return [], set()
    logger(f"Funcionários detectados: {len(unique_employees)}")
    existing_matriculas = db_manager.get_all_funcionarios_matriculas()
    new_employees_list = []
    processed_matriculas_in_file = set()
    for matricula, nome in unique_employees:
        processed_matriculas_in_file.add(matricula)
        if matricula not in existing_matriculas:
            new_employees_list.append((matricula, nome))
    for matricula, dias in sorted(employees_points_raw.items()):
        func_info = db_manager.get_funcionario_info(matricula)
        sector = func_info.get('setor', 'N/D')
        for data, pontos_brutos in sorted(dias.items()):
            pontos_brutos.sort(key=lambda x: x["datetime"])
            periodos_trabalhados, minutos_trabalhados_decimal = [], 0
            horarios_sequenciais = [p["datetime"] for p in pontos_brutos]
            if len(horarios_sequenciais) % 2 != 0:
                logger(f"AVISO: {matricula} {data}: Batidas ímpares.")
                horarios_sequenciais.pop()
            for i in range(0, len(horarios_sequenciais), 2):
                entrada, saida = horarios_sequenciais[i], horarios_sequenciais[i+1]
                turno = "Manhã" if i == 0 else "Tarde"
                jornada_inicio = datetime.strptime(f"{data} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                if saida < entrada: saida += timedelta(days=1)
                minutes_late = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                delay_deduction_minutes = calculate_deduction(minutes_late, sector)
                duration_minutes_bruto = (saida - entrada).total_seconds() / 60
                duration_minutes_liquido = max(0, duration_minutes_bruto - delay_deduction_minutes)
                minutos_trabalhados_decimal += duration_minutes_liquido
                periodos_trabalhados.append({"entrada": str(entrada), "saida": str(saida), "minutos_brutos": format_minutes_to_hms(duration_minutes_bruto), "deducao_minutos": format_minutes_to_hms(delay_deduction_minutes), "minutos_liquidos": format_minutes_to_hms(duration_minutes_liquido)})
            if periodos_trabalhados:
                db_manager.insert_horas_trabalhadas({"matricula": matricula, "data": data, "minutos_totais": format_minutes_to_hms(minutos_trabalhados_decimal), "periodos": periodos_trabalhados})
    return new_employees_list, processed_matriculas_in_file


class DateRangePicker:
    """Um widget de calendário reutilizável que seleciona um intervalo de datas."""
    def __init__(self, parent, bg_color, style_colors):
        self.frame = tk.Frame(parent, bg=bg_color)
        self.selected_start_date = None
        self.selected_end_date = None
        self.selecting_start = True
        
        self.style_colors = style_colors

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
        

class App:
    def __init__(self, root):
        self.db = DatabaseManager()
        self.root = root
        self.root.state('zoomed')
        self.root.title("WN Ponto Certo")
        self.root.configure(bg="#0a192f")
        self.root.minsize(1200, 700)
        self.selected_start_date = date.today()
        self.selected_end_date = date.today()
        self.selecting_start = True
        self.unsaved_edits = {}
        self.editing_widgets = {}
        self.setup_styles()
        self.setup_ui()

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
        style.configure("Treeview", rowheight=25, fieldbackground=self.LIGHT_BG, background=self.LIGHT_BG, foreground=self.FG_COLOR)
        style.configure("Treeview.Heading", font=('Segoe UI', 10, 'bold'), background=self.ACCENT_COLOR, foreground='white')
        style.map("Treeview.Heading", background=[('active', self.ACCENT_COLOR)])
        style.map('Treeview', background=[('selected', self.ACCENT_COLOR)])
        style.configure('TEntry', fieldbackground=self.LIGHT_BG, foreground=self.FG_COLOR, insertcolor=self.FG_COLOR)
        style.map('TEntry', fieldbackground=[('disabled', '#0a192f')], foreground=[('disabled', '#6a7b9d')])
        style.configure('TCombobox', fieldbackground=self.LIGHT_BG, background=self.LIGHT_BG, arrowcolor=self.FG_COLOR, foreground=self.FG_COLOR, selectbackground=self.LIGHT_BG, selectforeground=self.FG_COLOR)
        self.root.option_add('*TCombobox*Listbox.background', self.LIGHT_BG)
        self.root.option_add('*TCombobox*Listbox.foreground', self.FG_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', self.ACCENT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectForeground', self.FG_COLOR)
        style.configure('TLabelframe', background=self.BG_COLOR, bordercolor=self.ACCENT_COLOR)
        style.configure('TLabelframe.Label', foreground=self.HIGHLIGHT_COLOR, background=self.BG_COLOR, font=('Segoe UI', 9, 'bold'))
        style.configure('DateRange.TLabel', background=self.RANGE_BG_COLOR, foreground=self.FG_COLOR)
        style.configure('StartDate.TLabel', background=self.START_DATE_COLOR, foreground='white', font=('Segoe UI', 10, 'bold'))
        style.configure('EndDate.TLabel', background=self.END_DATE_COLOR, foreground='white', font=('Segoe UI', 10, 'bold'))

    # AJUSTE 3: Modificação do Layout Principal (setup_ui)
    def setup_ui(self):
        main_frame = tk.Frame(self.root, bg="#0a192f")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Configura as colunas e linhas do main_frame
        main_frame.grid_rowconfigure(1, weight=1) # Linha 1 (Panorama e Log) vai expandir
        main_frame.grid_columnconfigure(0, weight=3) # Col 0 (Panorama) 75%
        main_frame.grid_columnconfigure(1, weight=1) # Col 1 (Log) 25%

        # --- Top Frame (Linha 0, Colspan 2) ---
        top_frame = tk.Frame(main_frame, bg="#0a192f")
        top_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        
        header_frame = tk.Frame(top_frame, bg="#0a192f")
        header_frame.pack(fill=tk.X)
        try:
            logo_img = Image.open(LOGO_PATH)
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
        ttk.Button(actions_frame, text="📄 Exportar Log", command=self.on_export_log, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="🚪 Sair", command=self.root.quit, style='TButton').pack(side=tk.RIGHT)
        
        # --- Log Frame (Linha 1, Col 1) ---
        log_frame = ttk.LabelFrame(main_frame, text=" Log ", style='TLabelframe')
        log_frame.grid(row=1, column=1, sticky="nsew", pady=5, padx=(5, 0))
        self.log_area = scrolledtext.ScrolledText(log_frame, bg="#112240", fg="#a8b2d1", insertbackground="white", font=("Consolas", 9), relief=tk.FLAT, borderwidth=5)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        # --- Panorama Frame (Linha 1, Col 0) ---
        self.setup_point_viewer(main_frame)

    def on_import(self):
        filepath = filedialog.askopenfilename(title="Selecione o arquivo TXT", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not filepath: return
        try:
            self.append_log(f"Arquivo selecionado: {filepath}")
            self.append_log("Iniciando importação...")
            new_employees, processed_matriculas = import_glog_txt(filepath, self.db, logger=self.append_log)
            if new_employees:
                self.append_log(f"{len(new_employees)} novos funcionários. Complete o cadastro.")
                for matricula, nome in new_employees:
                    self.prompt_for_new_employee_details(matricula, nome)
                self.append_log("Cadastro concluído.")
            if processed_matriculas:
                self.append_log(f"Recalculando saldos para {len(processed_matriculas)} funcionários...")
                for matricula in processed_matriculas:
                    self.db.recalculate_full_balance_for_employee(matricula)
                self.append_log("Saldos recalculados.")
            self.append_log("Importação concluída ✅")
            self.update_employee_filter()
            self.load_point_viewer(force_reload=True)
            self._update_calendar_tags()
        except Exception as e:
            self.append_log(f"Erro importação: {e}")
            messagebox.showerror("Erro", str(e))

    def prompt_for_new_employee_details(self, matricula, nome):
        win = tk.Toplevel(self.root); win.title("Novo Funcionário"); win.geometry("500x300"); win.configure(bg=self.BG_COLOR); win.resizable(False, False); win.transient(self.root); win.grab_set()
        frame_form = tk.Frame(win, bg=self.BG_COLOR); frame_form.pack(padx=20, pady=20, fill="both", expand=True)
        tk.Label(frame_form, text="Complete o cadastro:", bg=self.BG_COLOR, fg=self.HIGHLIGHT_COLOR, font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10)); tk.Label(frame_form, text=f"Matrícula: {matricula}", bg=self.BG_COLOR, fg=self.FG_COLOR).pack(anchor="w"); tk.Label(frame_form, text=f"Nome: {nome}", bg=self.BG_COLOR, fg=self.FG_COLOR).pack(anchor="w", pady=(0, 20))
        frame_fichado = tk.Frame(frame_form, bg=self.BG_COLOR); frame_fichado.pack(fill='x', pady=5); tk.Label(frame_fichado, text="É Fichado?", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); cmb_fichado = ttk.Combobox(frame_fichado, values=LISTA_FICHADO, state="readonly", width=20); cmb_fichado.pack(side=tk.LEFT); cmb_fichado.set("Sim")
        frame_setor = tk.Frame(frame_form, bg=self.BG_COLOR); frame_setor.pack(fill='x', pady=5); tk.Label(frame_setor, text="Setor:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 10, "bold"), width=15, anchor='w').pack(side=tk.LEFT); cmb_setor = ttk.Combobox(frame_setor, values=LISTA_SETORES, state="readonly", width=20); cmb_setor.pack(side=tk.LEFT); cmb_setor.set("Produtivo")
        def save_new_employee():
            fichado_str = cmb_fichado.get(); setor = cmb_setor.get();
            if not fichado_str or not setor: messagebox.showerror("Erro", "Campos obrigatórios.", parent=win); return
            fichado_val = 1 if fichado_str == "Sim" else 0; dados = {"matricula": matricula, "nome": nome, "fichado": fichado_val, "setor": setor}
            try: self.db.insert_funcionario(dados); self.append_log(f"Funcionário {nome} ({matricula}) cadastrado."); win.destroy()
            except Exception as e: messagebox.showerror("Erro", f"Não foi possível salvar: {e}", parent=win)
        btn_salvar = ttk.Button(frame_form, text="✅ Salvar", style='TButton', command=save_new_employee); btn_salvar.pack(pady=20)
        self.root.wait_window(win)

    def on_edit_employee(self):
        win = tk.Toplevel(self.root); win.title("Editar Dados Cadastrais"); win.geometry("600x600"); win.configure(bg=self.BG_COLOR); win.resizable(False, False); win.transient(self.root); win.grab_set()
        selected_matricula = tk.StringVar(); main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20); main_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame = ttk.LabelFrame(main_frame, text=" Selecione um funcionário", style='TLabelframe'); tree_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15)); tree_frame.grid_rowconfigure(0, weight=1); tree_frame.grid_columnconfigure(0, weight=1)
        columns = ("Matrícula", "Nome", "Fichado", "Setor"); employee_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=employee_tree.yview); h_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=employee_tree.xview)
        employee_tree.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set); employee_tree.grid(row=0, column=0, sticky='nsew'); v_scroll.grid(row=0, column=1, sticky='ns'); h_scroll.grid(row=1, column=0, sticky='ew')
        col_widths = {"Matrícula": 100, "Nome": 250, "Fichado": 80, "Setor": 120}; [employee_tree.heading(col, text=col) or employee_tree.column(col, width=col_widths.get(col, 100), anchor=tk.W, stretch=tk.YES if col=="Nome" else tk.NO) for col in columns]
        edit_frame = ttk.LabelFrame(main_frame, text=" Editar Informações", style='TLabelframe'); edit_frame.pack(fill=tk.X)
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
                if self.db.update_employee_details(matricula, fichado_val, setor): messagebox.showinfo("Sucesso", "Dados atualizados!", parent=win); refresh_employee_list(); employee_tree.selection_remove(employee_tree.selection()); selected_matricula.set(""); cmb_fichado.set(""); cmb_setor.set(""); btn_salvar.config(state="disabled")
                else: messagebox.showerror("Erro", "Não foi possível salvar.", parent=win)
        btn_salvar.config(command=save_changes); refresh_employee_list()

    def on_add_punishment(self):
        win = tk.Toplevel(self.root); win.title("Adicionar Punição"); win.geometry("550x550"); win.configure(bg=self.BG_COLOR); win.resizable(False, False); win.transient(self.root); win.grab_set()
        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20); main_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(main_frame, text="1. Func:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]; cmb_func = ttk.Combobox(main_frame, values=nomes, state="readonly", width=50); cmb_func.pack(anchor="w", pady=(0, 15))
        tk.Label(main_frame, text="2. Data:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); cal_punicao = Calendar(main_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080"); cal_punicao.pack(anchor="w", pady=(0, 15))
        tk.Label(main_frame, text="3. Tempo (HH:MM):", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); entry_tempo = ttk.Entry(main_frame, width=15); entry_tempo.pack(anchor="w", pady=(0, 15))
        tk.Label(main_frame, text="4. Motivo:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); entry_motivo = ttk.Entry(main_frame, width=50); entry_motivo.pack(anchor="w", fill="x", pady=(0, 20))
        def save_punishment():
            selection = cmb_func.get();
            if not selection: messagebox.showerror("Erro", "Funcionário não selecionado.", parent=win); return
            matricula = selection.split(" - ")[0]; nome_func = " ".join(selection.split(" - ")[1:])
            data_str = cal_punicao.get_date(); tempo_str = entry_tempo.get().strip(); motivo = entry_motivo.get().strip()
            if not tempo_str: messagebox.showerror("Erro", "Tempo obrigatório.", parent=win); return
            if not motivo: messagebox.showerror("Erro", "Motivo obrigatório.", parent=win); return
            minutos_descontados = 0
            if re.match(r'^\d{1,3}:\d{2}$', tempo_str):
                try: h, m = map(int, tempo_str.split(':')); minutos_descontados = h * 60 + m
                except: messagebox.showerror("Erro", "Tempo inválido HH:MM.", parent=win); return
            elif re.match(r'^\d{1,3}:\d{2}:\d{2}$', tempo_str):
                try: h, m, s = map(int, tempo_str.split(':')); minutos_descontados = h * 60 + m + s / 60.0
                except: messagebox.showerror("Erro", "Tempo inválido HH:MM:SS.", parent=win); return
            else: messagebox.showerror("Erro", "Formato HH:MM.", parent=win); return
            if minutos_descontados <= 0: messagebox.showerror("Erro", "Tempo > 0.", parent=win); return
            confirm_msg = (f"Confirmar {format_minutes_to_hms(minutos_descontados)} para {nome_func}\nData: {datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')}?\nMotivo: {motivo}\n\nDesconto IMEDIATO do BH.")
            if messagebox.askyesno("Confirmar Punição", confirm_msg, parent=win):
                if self.db.add_punicao(matricula, data_str, minutos_descontados, motivo): messagebox.showinfo("Sucesso", "Punição registrada e BH atualizado!", parent=win); self.append_log(f"PUNIÇÃO: {matricula} - {data_str} - {format_minutes_to_hms(minutos_descontados)} - {motivo}"); cmb_func.set(''); entry_tempo.delete(0, 'end'); entry_motivo.delete(0, 'end'); self.load_point_viewer(force_reload=True); self._update_calendar_tags()
                else: messagebox.showerror("Erro", "Não foi possível salvar.", parent=win)
        btn_salvar_punicao = ttk.Button(main_frame, text="✅ Salvar Punição e Descontar BH", style='TButton', command=save_punishment); btn_salvar_punicao.pack()

    def on_manage_holidays(self):
        win = tk.Toplevel(self.root); win.title("Gerenciar Feriados"); win.geometry("550x480"); win.configure(bg=self.BG_COLOR); win.resizable(False, False); win.transient(self.root); win.grab_set()
        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20); main_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(main_frame, text="1. Data:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); cal_feriado = Calendar(main_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080"); cal_feriado.pack(anchor="w", pady=(0, 15))
        tk.Label(main_frame, text="2. Descrição:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); entry_descricao = ttk.Entry(main_frame, width=50); entry_descricao.pack(anchor="w", fill="x", pady=(0, 15))
        tk.Label(main_frame, text="3. Tipo:", bg=self.BG_COLOR, fg=self.FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); cmb_tipo = ttk.Combobox(main_frame, values=LISTA_TIPO_FERIADO, state="readonly", width=48); cmb_tipo.pack(anchor="w"); cmb_tipo.set("Municipal")
        def save_holiday():
            data_str = cal_feriado.get_date(); descricao = entry_descricao.get().strip(); tipo = cmb_tipo.get()
            if not descricao: messagebox.showerror("Erro", "Descrição obrigatória.", parent=win); return
            if not tipo: messagebox.showerror("Erro", "Tipo obrigatório.", parent=win); return
            if self.db.add_holiday(data_str, descricao, tipo):
                messagebox.showinfo("Sucesso", f"Feriado '{descricao}' {data_str} salvo!", parent=win); self.append_log(f"FERIADO: {data_str} - {descricao} ({tipo})"); entry_descricao.delete(0, 'end'); cmb_tipo.set("Municipal")
                if messagebox.askyesno("Recalcular Saldos", "Feriado salvo. Recalcular saldo de todos os funcionários para aplicar a nova regra?"):
                    self.append_log("Recalculando saldos devido a novo feriado..."); [self.db.recalculate_full_balance_for_employee(emp['matricula']) for emp in self.db.get_all_funcionarios()]; self.append_log("Recálculo completo."); messagebox.showinfo("Concluído", "Saldos recalculados.")
                self._update_calendar_tags(); self.load_point_viewer(force_reload=True)
            else: messagebox.showerror("Erro", "Não foi possível salvar.", parent=win)
        btn_salvar = ttk.Button(main_frame, text="✅ Salvar Feriado", style='TButton', command=save_holiday); btn_salvar.pack(pady=20)

    def on_extra_payment(self, *args):
        win = tk.Toplevel(self.root)
        win.title("Pagamento e Saldos")
        win.geometry("700x750")
        win.configure(bg=self.BG_COLOR)
        win.resizable(False, True)
        win.transient(self.root)
        win.grab_set()

        main_frame = tk.Frame(win, bg=self.BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

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

        def clear_details_frame():
            for widget in details_frame.winfo_children():
                widget.destroy()
            widgets.clear()
            data_vars["fichado_info"].clear()
            data_vars["nao_fichado_info"].clear()

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
                        story.append(Image(LOGO_PATH, width=4.5*cm, height=4.5*cm, hAlign='LEFT'))
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

                story.append(Paragraph("<b>Saldos Remanescentes (Após Pagamento)</b>", styles['h2']))
                story.append(Paragraph(f"<b>Extras:</b> {int(func_info.get('extras_disponiveis', 0))}", styles['Normal']))
                story.append(Paragraph(f"<b>Banco de Horas:</b> {format_minutes_to_hms(func_info.get('banco_horas', 0))}", styles['Normal']))
                
                # AJUSTE 1: Adicionar linha de Assinatura
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
                'pay_partial_salary': data_vars["partial_salary_var"].get() == "Sim"
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
                    
                    payment_details['salario_mensal'] = salario_mensal
                    payment_details['start_date'] = start_date
                    payment_details['end_date'] = end_date

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
                        story.append(Image(LOGO_PATH, width=4.5*cm, height=4.5*cm, hAlign='LEFT'))
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

                story.append(Paragraph("<b>Saldos Remanescentes (Após Pagamento)</b>", styles['h2']))
                story.append(Paragraph(f"<b>Banco de Horas:</b> {format_minutes_to_hms(func_info.get('banco_horas', 0))}", styles['Normal']))
                story.append(Paragraph(f"<b>Extras:</b> {int(func_info.get('extras_disponiveis', 0))}", styles['Normal']))

                # AJUSTE 1: Adicionar linha de Assinatura
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
                    'extras_valor': extras_valor
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
            
            date_picker = DateRangePicker(frame_parcial_widgets, self.BG_COLOR, self.style_colors_dict)
            date_picker.pack(pady=10)
            
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

            date_picker = DateRangePicker(frame_diarias, self.BG_COLOR, self.style_colors_dict)
            date_picker.pack(pady=10)
            
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
        win = tk.Toplevel(self.root); win.title("Exportar Log"); win.geometry("700x350"); win.configure(bg="#0a192f"); win.resizable(False, False); win.transient(self.root); win.grab_set()
        main_frame = tk.Frame(win, bg="#0a192f", padx=20, pady=20); main_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(main_frame, text="1. Func:", bg="#0a192f", fg="#ccd6f6", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5)); nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]; cmb_func = ttk.Combobox(main_frame, values=nomes, state="readonly", width=50); cmb_func.pack(anchor="w", pady=(0, 20)); tk.Label(main_frame, text="2. Período:", bg="#0a192f", fg="#ccd6f6", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))
        period_frame = tk.Frame(main_frame, bg="#0a192f"); period_frame.pack(anchor="w"); tk.Label(period_frame, text="De:", bg="#0a192f", fg="#ccd6f6").pack(side=tk.LEFT, padx=(0,5)); cal_start = Calendar(period_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080"); cal_start.pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(period_frame, text="Até:", bg="#0a192f", fg="#ccd6f6").pack(side=tk.LEFT, padx=(0,5)); cal_end = Calendar(period_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080"); cal_end.pack(side=tk.LEFT); btn_export = ttk.Button(main_frame, text="Gerar PDF", style='TButton'); btn_export.pack(pady=20)
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
            except Exception as e:
                messagebox.showerror("Erro", f"Datas inválidas: {e}", parent=win)
                return

            logs = self.db.get_logs_for_period(matricula, start_date_str, end_date_str)
            if not logs: messagebox.showinfo("Aviso", "Nenhum log encontrado.", parent=win); return
            
            filepath = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")], title="Salvar Relatório", initialfile=f"Log_{nome_func.replace(' ','_')}_{start_date_str}_a_{end_date_str}.pdf")
            if not filepath: return
            try:
                doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm); styles = getSampleStyleSheet(); story = []
                story.append(Paragraph("Relatório Log Alterações", styles['h1'])); story.append(Spacer(1, 0.5*cm)); story.append(Paragraph(f"<b>Funcionário:</b> {nome_func}", styles['Normal'])); story.append(Paragraph(f"<b>Matrícula:</b> {matricula}", styles['Normal'])); story.append(Paragraph(f"<b>Período:</b> {start_dt.strftime('%d/%m/%Y')} a {end_dt.strftime('%d/%m/%Y')}", styles['Normal'])); story.append(Spacer(1, 1*cm))
                table_data = [['Data Ponto', 'Data Edição', 'Valor Antigo', 'Valor Novo', 'Justificativa']]; [table_data.append([datetime.strptime(log['data_ponto'], '%Y-%m-%d').strftime('%d/%m/%Y'), datetime.strptime(log['data_edicao'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M'), log['periodos_antigos'], log['periodos_novos'], log['justificativa']]) for log in logs]
                t = Table(table_data, colWidths=[2.5*cm, 3*cm, 3*cm, 3*cm, 5*cm]); t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.teal), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0,0), (-1,0), 12), ('BACKGROUND', (0,1), (-1,-1), colors.beige), ('GRID', (0,0), (-1,-1), 1, colors.black)]))
                story.append(t); doc.build(story); messagebox.showinfo("Sucesso", f"Relatório salvo:\n{filepath}", parent=win); win.destroy()
            except Exception as e: messagebox.showerror("Erro PDF", f"Erro: {e}", parent=win)
        btn_export.config(command=generate_pdf)

    # AJUSTE 3: Modificação do Layout do Panorama (setup_point_viewer)
    def setup_point_viewer(self, parent_frame):
        # O frame_viewer agora está em main_frame (row 1, col 0)
        frame_viewer = ttk.LabelFrame(parent_frame, text=" Panorama ", style='TLabelframe')
        frame_viewer.grid(row=1, column=0, sticky="nsew", pady=5, padx=(0, 5))
        
        # Configuração de expansão: Linha 3 (Treeview) vai expandir
        frame_viewer.grid_rowconfigure(3, weight=5)
        frame_viewer.grid_columnconfigure(0, weight=1) 
        
        # --- Controles (Linha 0) ---
        frame_controls = tk.Frame(frame_viewer, bg="#0a192f"); 
        frame_controls.grid(row=0, column=0, sticky="ew", pady=(5,0), padx=10)
        tk.Label(frame_controls, text="Funcionário:", bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(0,5))
        self.cmb_filter_func = ttk.Combobox(frame_controls, state="readonly", width=40)
        self.cmb_filter_func.pack(side=tk.LEFT, padx=(0, 20))
        self.cmb_filter_func.bind("<<ComboboxSelected>>", lambda e: self.load_point_viewer(force_reload=True))
        
        action_button_frame = tk.Frame(frame_controls, bg="#0a192f")
        action_button_frame.pack(side=tk.RIGHT)
        ttk.Button(action_button_frame, text="Atualizar", command=self.load_point_viewer).pack(side=tk.LEFT, padx=5)
        
        # AJUSTE 2: Novo botão de Exportar Ponto
        ttk.Button(action_button_frame, text="📄 Exportar Ponto", command=self.on_export_panorama).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(action_button_frame, text="💾 Salvar", command=self.commit_all_changes).pack(side=tk.LEFT, padx=5)
        
        # --- Frame do Calendário (Linha 1) - Reestruturado com Grid ---
        calendar_frame = tk.Frame(frame_viewer, bg="#0a192f")
        calendar_frame.grid(row=1, column=0, sticky="ew", pady=5, padx=10)
        calendar_frame.grid_columnconfigure(1, weight=1)
        calendar_frame.grid_columnconfigure(2, weight=1)
        calendar_frame.grid_rowconfigure(1, weight=1) # Faz as listas expandirem

        self.main_calendar = Calendar(calendar_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', 
                                      background="#008080", foreground="white", headersbackground="#008080", 
                                      normalbackground="#112240", weekendbackground="#172a45", 
                                      othermonthbackground="#0a192f", othermonthforeground="#6a7b9d", 
                                      selectbackground=self.ACCENT_COLOR)
        self.main_calendar.grid(row=0, column=0, rowspan=2, padx=(0, 20), sticky='n')
        self.main_calendar.bind("<<CalendarSelected>>", self.on_calendar_click)
        self.main_calendar.bind("<<CalendarMonthChanged>>", self.on_calendar_month_changed) 
        
        self.main_calendar.tag_config('start_date', background=self.START_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('end_date', background=self.END_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('range_date', background=self.RANGE_BG_COLOR, foreground='#ccd6f6')
        self.main_calendar.tag_config('holiday', background=self.HOLIDAY_COLOR, foreground='white') 
        
        # --- Labels de Período (Canto superior direito do calendário) ---
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

        # --- Lista de Feriados (Meio, Coluna 1) ---
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

        # --- Lista de Punições (Meio, Coluna 2) ---
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
        
        # --- Saldos (Linha 2) ---
        frame_saldos = ttk.LabelFrame(frame_viewer, text=" Saldos Atuais", style='TLabelframe')
        frame_saldos.grid(row=2, column=0, sticky="ew", pady=(10, 5), padx=10)
        tk.Label(frame_saldos, text="BH:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(10,0)); self.lbl_saldo_bh_total = tk.Label(frame_saldos, text="--:--:--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_saldo_bh_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Extras:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_saldo_extras_total = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_saldo_extras_total.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Fichado:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_fichado_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w"); self.lbl_fichado_status.pack(side=tk.LEFT, padx=(5, 20)); tk.Label(frame_saldos, text="Setor:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT); self.lbl_setor_status = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w"); self.lbl_setor_status.pack(side=tk.LEFT, padx=5)
        
        # --- Treeview (Linha 3) ---
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
        
        col_widths = {"Matrícula": 80, "Nome": 200, "Data": 100, "E1": 60, "S1": 60, "E2": 60, "S2": 60, "Carga_Horaria": 110, "Punição": 100, "Total_Desconto": 110}
        for col in columns:
            anchor = tk.W if col == "Nome" else tk.CENTER
            self.tree_viewer.heading(col, text=col.replace('_', ' ').replace('Carga Horaria', 'Carga Horária'))
            self.tree_viewer.column(col, width=col_widths.get(col, 100), anchor=anchor, stretch=tk.NO)
        
        self.tree_viewer.bind('<ButtonRelease-1>', self.start_in_place_edit)
        self.tree_viewer.tag_configure('evenrow', background='#112240')
        self.tree_viewer.tag_configure('oddrow', background='#172a45')
        
        self.update_employee_filter()
        self._update_calendar_tags()
        self.load_point_viewer(force_reload=True)

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
        
        panorama_data = self.db.get_point_panorama(start_date, end_date, target_matricula)
        
        for i, item in enumerate(panorama_data):
            data_db_str = item['Data']; data_ptbr = datetime.strptime(data_db_str, "%Y-%m-%d").strftime("%d/%m/%Y") if data_db_str else data_db_str
            punicao_minutos = self.db.get_total_punishment_minutes_for_day(item['Matricula'], data_db_str); punicao_hms = format_minutes_to_hms(punicao_minutos) if punicao_minutos > 0 else "00:00:00"
            values = (item['Matricula'], item['Nome'], data_ptbr, item['E1'], item['S1'], item['E2'], item['S2'], item['Carga_Horaria'], punicao_hms, item['Total_Desconto'])
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'; self.tree_viewer.insert("", "end", values=values, iid=(item['Matricula'], item['Data']), tags=(tag,))
        
        if target_matricula: 
            func_info = self.db.get_funcionario_info(target_matricula); saldo_bh = func_info.get('banco_horas', 0); saldo_extras = func_info.get('extras_disponiveis', 0); self.lbl_saldo_bh_total.config(text=format_minutes_to_hms(saldo_bh)); self.lbl_saldo_extras_total.config(text=str(int(saldo_extras))); fichado_val = func_info.get('fichado', 0); fichado_str = "Sim" if fichado_val == 1 else "Não"; setor_str = func_info.get('setor', 'N/D'); self.lbl_fichado_status.config(text=fichado_str); self.lbl_setor_status.config(text=setor_str)
        else: 
            self.lbl_saldo_bh_total.config(text="--:--:--"); self.lbl_saldo_extras_total.config(text="--"); self.lbl_fichado_status.config(text="--"); self.lbl_setor_status.config(text="--")
        
        if start_date and end_date and hasattr(self, 'holiday_listbox'): 
            holidays = self.db.get_holidays_in_range(start_date, end_date); [self.holiday_listbox.insert(tk.END, f"{datetime.strptime(h['data'], '%Y-%m-%d').strftime('%d/%m/%Y')} - {h['descricao']} ({h['tipo']})") for h in holidays if h.get('data')]
        
        if target_matricula and start_date and end_date and hasattr(self, 'punishment_listbox'): 
            punishments = self.db.get_punishments_in_range(target_matricula, start_date, end_date); total_punishments = len(punishments); self.lbl_total_punishments.config(text=f"Total Punições: {total_punishments}"); [self.punishment_listbox.insert(tk.END, f"{datetime.strptime(p['data_punicao'], '%Y-%m-%d').strftime('%d/%m/%Y')} - {format_minutes_to_hms(p['minutos_descontados'])} - {p.get('motivo','Sem motivo')}") for p in punishments if p.get('data_punicao')]
        elif hasattr(self, 'punishment_listbox'): 
            self.punishment_listbox.delete(0, tk.END); self.lbl_total_punishments.config(text="Total Punições: --")

    # AJUSTE 2: Nova função para exportar o panorama
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
            # Usar paisagem (landscape) para caber as colunas
            doc = SimpleDocTemplate(filepath, pagesize=landscape(A4), rightMargin=1.5*cm, leftMargin=1.5*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
            styles = getSampleStyleSheet()
            story = []

            # Estilos
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
            
            style_nome = TableStyle([('ALIGN', (0,0), (0,0), 'LEFT'),
                                     ('ALIGN', (1,0), (1,0), 'RIGHT')])
            
            # --- Cabeçalho ---
            if LOGO_PATH.exists():
                story.append(Image(LOGO_PATH, width=3*cm, height=3*cm, hAlign='LEFT'))
                story.append(Spacer(1, 0.2*cm))

            story.append(Paragraph("Espelho de Ponto", style_title))
            story.append(Spacer(1, 1*cm))
            
            # --- Informações ---
            story.append(Paragraph(f"<b>Período:</b> {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')}", styles['Normal']))
            
            if target_matricula != "Todos":
                story.append(Paragraph(f"<b>Funcionário:</b> {nome_func} (Mat. {target_matricula})", styles['Normal']))
                story.append(Spacer(1, 0.5*cm))
                
                # Tabela de Saldos
                saldo_data = [
                    [Paragraph(f"<b>BH:</b> {self.lbl_saldo_bh_total.cget('text')}", style_header),
                     Paragraph(f"<b>Extras:</b> {self.lbl_saldo_extras_total.cget('text')}", style_header),
                     Paragraph(f"<b>Fichado:</b> {self.lbl_fichado_status.cget('text')}", style_header),
                     Paragraph(f"<b>Setor:</b> {self.lbl_setor_status.cget('text')}", style_header)]
                ]
                saldo_table = Table(saldo_data, colWidths=[6*cm, 6*cm, 6*cm, 8*cm])
                saldo_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
                story.append(saldo_table)

            story.append(Spacer(1, 1*cm))

            # --- Tabela de Dados ---
            # ("Matrícula", "Nome", "Data", "E1", "S1", "E2", "S2", "Carga_Horaria", "Punição", "Total_Desconto")
            col_headers = ["Mat.", "Nome", "Data", "E1", "S1", "E2", "S2", "Carga", "Punição", "Desconto"]
            table_data = [[Paragraph(h, style_table_header) for h in col_headers]]
            
            col_widths = [1.8*cm, 5.5*cm, 2.5*cm, 1.8*cm, 1.8*cm, 1.8*cm, 1.8*cm, 2.5*cm, 2.5*cm, 2.5*cm]

            for item_id in data_rows:
                values = self.tree_viewer.item(item_id, 'values')
                # Formata os dados para o PDF
                row_data = [
                    Paragraph(values[0], style_table_body), # Matrícula
                    Paragraph(values[1], style_table_body), # Nome
                    Paragraph(values[2], style_table_body), # Data
                    Paragraph(values[3], style_table_body), # E1
                    Paragraph(values[4], style_table_body), # S1
                    Paragraph(values[5], style_table_body), # E2
                    Paragraph(values[6], style_table_body), # S2
                    Paragraph(values[7], style_table_body), # Carga_Horaria
                    Paragraph(values[8], style_table_body), # Punição
                    Paragraph(values[9], style_table_body), # Total_Desconto
                ]
                table_data.append(row_data)

            t = Table(table_data, colWidths=col_widths)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.teal),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('BOX', (0,0), (-1,-1), 1, colors.black),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('ALIGN', (0,1), (0,-1), 'LEFT'), # Alinha matrícula à esquerda
                ('ALIGN', (1,1), (1,-1), 'LEFT'), # Alinha nome à esquerda
            ]))
            story.append(t)
            
            # --- Assinatura (se for funcionário único) ---
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
        data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d"); entry_edit = ttk.Entry(self.tree_viewer); entry_edit.place(x=x, y=y, width=width, height=height)
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
                if new_time != current_time: messagebox.showerror("Erro Formato", "HH:MM.", parent=self.root); on_escape(); return
            temp_vals = list(self.tree_viewer.item(item_id, 'values')); temp_vals[col_index] = new_time; self.tree_viewer.item(item_id, values=tuple(temp_vals))
            if edit_key not in self.unsaved_edits: current_row_values = self.tree_viewer.item(item_id, 'values'); self.unsaved_edits[edit_key] = {'E1': current_row_values[3], 'S1': current_row_values[4], 'E2': current_row_values[5], 'S2': current_row_values[6]}
            self.unsaved_edits[edit_key][column_name] = new_time; self.unsaved_edits[edit_key]['justificativa'] = just; self.update_visual_work_hours(item_id)
            if from_cmb: on_escape()
        entry_edit.bind('<Return>', lambda e: handle_edit(from_cmb=True)); entry_edit.bind('<Escape>', on_escape); entry_edit.bind('<FocusOut>', lambda e: on_escape()); justificativa_cmb.bind('<<ComboboxSelected>>', lambda e: handle_edit(from_cmb=True)); justificativa_cmb.bind('<Escape>', on_escape)

    def update_visual_work_hours(self, item_id):
        values = self.tree_viewer.item(item_id, 'values'); matricula = values[0]; data_ptbr = values[2]; data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        all_times_raw = [values[3], values[4], values[5], values[6]]; func_info = self.db.get_funcionario_info(matricula); sector = func_info.get('setor', 'N/D'); minutos_totais = 0
        for i in range(0, 4, 2):
            e_time, s_time = all_times_raw[i], all_times_raw[i+1]
            if e_time and s_time and e_time not in ('N/A', '00:00', '') and s_time not in ('N/A', '00:00', ''):
                try:
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M"); saida = datetime.strptime(f"{data_db} {s_time}", "%Y-%m-%d %H:%M")
                    if saida < entrada: saida += timedelta(days=1)
                    turno = "Manhã" if i == 0 else "Tarde"; jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60); deduction_min = calculate_deduction(late_min, sector) 
                    bruto_min = (saida - entrada).total_seconds() / 60; liquido_min = max(0, bruto_min - deduction_min); minutos_totais += liquido_min
                except ValueError: continue
        new_values = list(values); new_values[7] = format_minutes_to_hms(minutos_totais); self.tree_viewer.item(item_id, values=tuple(new_values))

    def process_manual_update_and_save(self, matricula, data_db, all_times_raw, justificativa):
        func_info = self.db.get_funcionario_info(matricula); sector = func_info.get('setor', 'N/D'); periodos, minutos_totais = [], 0
        for i in range(0, 4, 2):
            e_time, s_time = all_times_raw[i], all_times_raw[i+1]
            if e_time and s_time and e_time not in ('N/A', '00:00', '') and s_time not in ('N/A', '00:00', ''):
                try:
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M"); saida = datetime.strptime(f"{data_db} {s_time}", "%Y-%m-%d %H:%M")
                    if saida < entrada: saida += timedelta(days=1)
                    turno = "Manhã" if i == 0 else "Tarde"; jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60); deduction_min = calculate_deduction(late_min, sector) 
                    bruto_min = (saida - entrada).total_seconds() / 60; liquido_min = max(0, bruto_min - deduction_min); minutos_totais += liquido_min
                    periodos.append({"entrada": str(entrada), "saida": str(saida), "minutos_brutos": format_minutes_to_hms(bruto_min), "deducao_minutos": format_minutes_to_hms(deduction_min), "minutos_liquidos": format_minutes_to_hms(liquido_min)})
                except ValueError: self.append_log(f"ERRO formato '{e_time}' ou '{s_time}'."); continue
        self.db.insert_horas_trabalhadas({"matricula": matricula, "data": data_db, "minutos_totais": format_minutes_to_hms(minutos_totais), "periodos": periodos}, justificativa=justificativa)
        self.append_log(f"Ponto {matricula} {data_db} atualizado. Just: '{justificativa}'.")

    def commit_all_changes(self):
        if self.editing_widgets: [w.event_generate('<FocusOut>') for k, w in self.editing_widgets.items() if k == 'entry']
        if not self.unsaved_edits: messagebox.showinfo("Salvar", "Nenhuma alteração."); return
        if not messagebox.askyesno("Confirmar", f"{len(self.unsaved_edits)} dia(s) alterados. Salvar e recalcular?"): return
        self.append_log(f"Salvando {len(self.unsaved_edits)} alterações..."); affected_employees = set()
        for (matricula, data_db), edits in self.unsaved_edits.items(): affected_employees.add(matricula); justificativa = edits.get('justificativa', 'Ajuste Manual'); self.process_manual_update_and_save(matricula, data_db, [edits['E1'], edits['S1'], edits['E2'], edits['S2']], justificativa)
        self.append_log("Recalculando saldos..."); [self.db.recalculate_full_balance_for_employee(mat) for mat in affected_employees]
        self.unsaved_edits = {}; messagebox.showinfo("Sucesso", "Alterações salvas e saldos recalculados.")
        self.load_point_viewer(force_reload=True); self._update_calendar_tags() 

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()