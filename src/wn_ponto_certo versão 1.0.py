import os
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
from collections import defaultdict
from datetime import datetime, timedelta, date # Import date
import sqlite3
import json
from pathlib import Path
from tkcalendar import Calendar
import re

# Tenta importar bibliotecas necessárias
try:
    from PIL import Image, ImageTk
except ImportError:
    messagebox.showerror("Biblioteca Faltando", "A biblioteca Pillow é necessária.\nPor favor, instale-a executando: pip install Pillow")
    exit()

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
except ImportError:
    messagebox.showerror("Biblioteca Faltando", "A biblioteca reportlab é necessária.\nPor favor, instale-a executando: pip install reportlab")
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

LISTA_JUSTIFICATIVAS = [
    "Ajuste de Ponto Manual (Erro de Batida)",
    "Funcionário iniciou o expediente externamente",
    "Falta justificada com atestado médico",
    "Saída Antecipada Justificada",
    "Esquecimento de Batida",
]

def try_parse_datetime(s, format_to_try="%Y-%m-%d %H:%M:%S"):
    try:
        return datetime.strptime(s, format_to_try)
    except (ValueError, IndexError):
        try: return datetime.strptime(s, "%Y/%m/%d %H:%M:%S")
        except:
            try: return datetime.strptime(s, "%Y/%m/%d %H:%M")
            except: return None

#punição por atraso
def calculate_deduction(minutes_late):
    minutes_late = max(0, minutes_late)
    
    if minutes_late <= 5:
        # Faixa 1: 0-5 min
        return 0
    elif minutes_late <= 15:
        # Faixa 2: 6-15 min
        return minutes_late * 3
    elif minutes_late <= 30:
        # Faixa 3: 16-30 min
        # Punição máxima da Faixa 2 (15 * 3)
        p1 = 15 * 3  # 45 minutos
        # Punição para os minutos excedentes (16-30) * 2
        p2 = (minutes_late - 15) * 2
        return p1 + p2
    else:
        # Faixa 4: Acima de 30 min
        # Punição máxima da Faixa 2 (15 * 3)
        p1 = 15 * 3  # 45 minutos
        # Punição máxima da Faixa 3 ((30-15) * 2)
        p2 = (30 - 15) * 2  # 30 minutos
        # Punição para os minutos excedentes (acima de 30) * 1
        p3 = (minutes_late - 30) * 1
        return p1 + p2 + p3

def format_minutes_to_hms(minutes):
    if minutes is None: return "00:00:00"
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    hours = int(minutes // 60)
    remaining_minutes = int(minutes % 60)
    seconds = int((minutes * 60) % 60)
    return f"{sign}{hours:02}:{remaining_minutes:02}:{seconds:02}"

def get_expected_daily_minutes(date_str):
    try:
        date_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_dt.weekday() < 5: return MINUTOS_JORNADA_SEG_SEX
        elif date_dt.weekday() == 5: return MINUTOS_JORNADA_SABADO
        else: return 0
    except ValueError: return 0

class DatabaseManager:
    # ... (restante da classe DatabaseManager permanece inalterado) ...
    def __init__(self, db_path=None):
        self.db_path = str(db_path if db_path else DEFAULT_DB)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_database()

    def create_database(self):
        c = self.conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS funcionarios (id INTEGER PRIMARY KEY, matricula TEXT UNIQUE, nome TEXT, salario REAL DEFAULT 0, banco_horas REAL DEFAULT 0, extras_disponiveis INTEGER DEFAULT 0)")
        c.execute("CREATE TABLE IF NOT EXISTS horas_trabalhadas (id INTEGER PRIMARY KEY, matricula TEXT, data TEXT, minutos_totais TEXT, periodos TEXT, criado_em DATETIME DEFAULT CURRENT_TIMESTAMP, UNIQUE(matricula, data))")
        c.execute("CREATE TABLE IF NOT EXISTS log_edicoes (id INTEGER PRIMARY KEY, matricula TEXT, data_ponto TEXT, data_edicao DATETIME DEFAULT CURRENT_TIMESTAMP, periodos_antigos TEXT, periodos_novos TEXT, justificativa TEXT, usuario TEXT DEFAULT 'SYSTEM/MANUAL')")
        self.conn.commit()

    def insert_funcionario(self, dados):
        self.conn.execute("INSERT OR IGNORE INTO funcionarios (matricula, nome) VALUES (?, ?)", (dados.get("matricula"), dados.get("nome")))
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

    def get_logs_for_period(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        query = """
            SELECT l.data_ponto, l.data_edicao, l.periodos_antigos, l.periodos_novos, l.justificativa, f.nome
            FROM log_edicoes l
            JOIN funcionarios f ON l.matricula = f.matricula
            WHERE l.matricula = ? AND l.data_ponto BETWEEN ? AND ?
            ORDER BY l.data_ponto, l.data_edicao
        """
        c.execute(query, (matricula, start_date, end_date))
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
        if not start_date or not end_date: # Adiciona verificação se datas existem
             return []
        
        # Converte para string se forem objetos date
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
        # Busca TODOS os registros do funcionário para calcular o saldo corretamente
        sql_todos_horas = f"SELECT matricula, data, periodos, minutos_totais FROM horas_trabalhadas WHERE matricula IN ({placeholders}) ORDER BY data ASC"
        c.execute(sql_todos_horas, matriculas_list)
        todos_os_dados_historicos = c.fetchall()
        
        panorama_final = []
        for func in funcionarios:
            if not func: continue
            
            matricula = func['matricula']
            
            info_final_real = self.get_funcionario_info(matricula)
            saldo_bh_real_final = info_final_real.get('banco_horas', 0)
            saldo_extras_real_final = info_final_real.get('extras_disponiveis', 0)

            # --- Cálculo do saldo simulado ---
            saldo_bh_simulado, saldo_extras_simulado = 0, 0
            historico_simulado = {}
            # Filtra dados históricos apenas para o funcionário atual
            dados_func = [r for r in todos_os_dados_historicos if r['matricula'] == matricula]

            for row in dados_func:
                bh_anterior_simulado = saldo_bh_simulado
                extras_anterior_simulado = saldo_extras_simulado
                
                try:
                    h, m, s = map(int, row['minutos_totais'].split(':'))
                    excedente_dia = (h * 60 + m + s / 60) - get_expected_daily_minutes(row['data'])
                    saldo_bh_simulado += excedente_dia
                    while saldo_bh_simulado >= MINUTOS_UNIDADE_EXTRA:
                        saldo_bh_simulado -= MINUTOS_UNIDADE_EXTRA
                        saldo_extras_simulado += 1
                    while saldo_bh_simulado < 0 and saldo_extras_simulado > 0:
                        saldo_bh_simulado += MINUTOS_UNIDADE_EXTRA
                        saldo_extras_simulado -= 1
                except: continue

                historico_simulado[row['data']] = {
                    'bh_anterior': bh_anterior_simulado, 'bh_saldo': saldo_bh_simulado,
                    'extras_anterior': extras_anterior_simulado, 'extras_saldo': saldo_extras_simulado
                }
            # --- Fim do cálculo simulado ---

            bh_diff = saldo_bh_real_final - saldo_bh_simulado
            extras_diff = saldo_extras_real_final - saldo_extras_simulado
            
            # --- Montagem do Panorama para o período selecionado ---
            current_date_iter = start_dt
            while current_date_iter <= end_dt:
                data_str = current_date_iter.isoformat()
                dados_do_dia = next((r for r in dados_func if r['data'] == data_str), None)
                simulacao_do_dia = historico_simulado.get(data_str)

                # Se não houver simulação EXATA para o dia, busca a do último dia ANTERIOR conhecido
                if not simulacao_do_dia:
                    last_sim_date = max((d for d in historico_simulado if d < data_str), default=None)
                    if last_sim_date:
                        # Para dias sem registro, o saldo não muda
                        simulacao_do_dia = {'bh_anterior': historico_simulado[last_sim_date]['bh_saldo'], 'bh_saldo': historico_simulado[last_sim_date]['bh_saldo'],
                                            'extras_anterior': historico_simulado[last_sim_date]['extras_saldo'], 'extras_saldo': historico_simulado[last_sim_date]['extras_saldo']}
                    else: # Se for o primeiro dia ou não houver histórico anterior
                        simulacao_do_dia = {'bh_anterior': 0, 'bh_saldo': 0, 'extras_anterior': 0, 'extras_saldo': 0}

                carga_horaria_dia_str, total_desconto, horarios = "00:00:00", "00:00:00", []
                if dados_do_dia:
                    carga_horaria_dia_str = dados_do_dia['minutos_totais']
                    total_desconto = self._get_daily_summary_for_display(matricula, data_str)[1]
                    try:
                        for p in json.loads(dados_do_dia['periodos']):
                            horarios.extend([datetime.strptime(p['entrada'], '%Y-%m-%d %H:%M:%S').strftime('%H:%M'), datetime.strptime(p['saida'], '%Y-%m-%d %H:%M:%S').strftime('%H:%M')])
                    except: pass
                
                ponto_dict = {'Matricula': matricula, 'Nome': func['nome'], 'Data': data_str, 'E1': '', 'S1': '', 'E2': '', 'S2': '', 
                              'Carga_Horaria': carga_horaria_dia_str, 'Total_Desconto': total_desconto, 
                              'BH_Anterior': format_minutes_to_hms(simulacao_do_dia['bh_anterior'] + bh_diff), 
                              'BH_Saldo': format_minutes_to_hms(simulacao_do_dia['bh_saldo'] + bh_diff), 
                              'Extras_Disp': str(int(simulacao_do_dia['extras_saldo'] + extras_diff))}
                
                if len(horarios) >= 1: ponto_dict['E1'] = horarios[0]
                if len(horarios) >= 2: ponto_dict['S1'] = horarios[1]
                if len(horarios) >= 3: ponto_dict['E2'] = horarios[2]
                if len(horarios) >= 4: ponto_dict['S2'] = horarios[3]
                panorama_final.append(ponto_dict)
                current_date_iter += timedelta(days=1)
            # --- Fim da montagem ---
        
        panorama_final.sort(key=lambda x: (x['Nome'], x['Data']))
        return panorama_final

    def update_saldos(self, matricula, minutos_a_deduzir_bh, unidades_a_deduzir_extras):
        try:
            info_antes = self.get_funcionario_info(matricula)
            saldo_bh_antes = info_antes.get('banco_horas', 0)
            saldo_extras_antes = info_antes.get('extras_disponiveis', 0)
            
            self.conn.execute("UPDATE funcionarios SET banco_horas = banco_horas - ?, extras_disponiveis = extras_disponiveis - ? WHERE matricula = ?", (minutos_a_deduzir_bh, unidades_a_deduzir_extras, matricula))
            self.conn.commit()

            data_hoje = datetime.now().strftime("%Y-%m-%d")
            justificativa = "Pagamento/Dedução de Saldo"
            periodo_antigo = f"BH: {format_minutes_to_hms(saldo_bh_antes)}, Extras: {int(saldo_extras_antes)}"
            periodo_novo = f"BH: {format_minutes_to_hms(saldo_bh_antes - minutos_a_deduzir_bh)}, Extras: {int(saldo_extras_antes - unidades_a_deduzir_extras)}"
            self.log_edicao(matricula, data_hoje, periodo_antigo, periodo_novo, justificativa)
            
            return True
        except Exception as e:
            print(f"Erro ao atualizar saldos: {e}")
            return False

    def recalculate_full_balance_for_employee(self, matricula):
        c = self.conn.cursor()
        c.execute("SELECT data, minutos_totais FROM horas_trabalhadas WHERE matricula = ? ORDER BY data ASC", (matricula,))
        all_work_days = c.fetchall()
        
        saldo_bh_minutos, saldo_extras = 0, 0
        for day in all_work_days:
            try:
                h, m, s = map(int, day['minutos_totais'].split(':'))
                excedente_dia = (h * 60 + m + s / 60) - get_expected_daily_minutes(day['data'])
                saldo_bh_minutos += excedente_dia
                while saldo_bh_minutos >= MINUTOS_UNIDADE_EXTRA:
                    saldo_bh_minutos -= MINUTOS_UNIDADE_EXTRA
                    saldo_extras += 1
                while saldo_bh_minutos < 0 and saldo_extras > 0:
                    saldo_bh_minutos += MINUTOS_UNIDADE_EXTRA
                    saldo_extras -= 1
            except: continue
        self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?", (saldo_bh_minutos, saldo_extras, matricula))
        self.conn.commit()

# ... (função import_glog_txt permanece inalterada) ...
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
        logger(f"ERRO CRÍTICO NA LEITURA DO ARQUIVO: {e}"); return
    
    logger(f"Funcionários detectados: {len(unique_employees)}")
    for matricula, nome in unique_employees: db_manager.insert_funcionario({"matricula": matricula, "nome": nome})

    for matricula, dias in sorted(employees_points_raw.items()):
        for data, pontos_brutos in sorted(dias.items()):
            pontos_brutos.sort(key=lambda x: x["datetime"])
            periodos_trabalhados, minutos_trabalhados_decimal = [], 0
            horarios_sequenciais = [p["datetime"] for p in pontos_brutos]
            if len(horarios_sequenciais) % 2 != 0:
                 logger(f"AVISO: {matricula} - {data}: Número ímpar de batidas. A última será ignorada.")
                 horarios_sequenciais.pop()
            
            for i in range(0, len(horarios_sequenciais), 2):
                entrada, saida = horarios_sequenciais[i], horarios_sequenciais[i+1]
                turno = "Manhã" if i == 0 else "Tarde"
                jornada_inicio = datetime.strptime(f"{data} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                if saida < entrada: saida += timedelta(days=1)
                minutes_late = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                delay_deduction_minutes = calculate_deduction(minutes_late)
                duration_minutes_bruto = (saida - entrada).total_seconds() / 60
                duration_minutes_liquido = max(0, duration_minutes_bruto - delay_deduction_minutes)
                minutos_trabalhados_decimal += duration_minutes_liquido
                periodos_trabalhados.append({"entrada": str(entrada), "saida": str(saida), "minutos_brutos": format_minutes_to_hms(duration_minutes_bruto), "deducao_minutos": format_minutes_to_hms(delay_deduction_minutes), "minutos_liquidos": format_minutes_to_hms(duration_minutes_liquido)})
            
            if periodos_trabalhados:
                db_manager.insert_horas_trabalhadas({"matricula": matricula, "data": data, "minutos_totais": format_minutes_to_hms(minutos_trabalhados_decimal), "periodos": periodos_trabalhados})
    
    logger("Recalculando saldos finais para todos os funcionários importados...")
    for matricula, _ in unique_employees:
        db_manager.recalculate_full_balance_for_employee(matricula)
    logger("Saldos recalculados.")

class App:
    def __init__(self, root):
        self.db = DatabaseManager()
        self.root = root
        self.root.state('zoomed') 
        self.root.title("WN Ponto Certo")
        self.root.configure(bg="#0a192f")
        self.root.minsize(1200, 700)

        # << CALENDÁRIO ÚNICO: Variáveis de estado >>
        self.selected_start_date = date.today() # Inicia com a data de hoje
        self.selected_end_date = date.today()   # Inicia com a data de hoje
        self.selecting_start = True # Próximo clique seleciona o início

        self.unsaved_edits = {} 
        self.editing_widgets = {}
        
        self.setup_styles()
        self.setup_ui()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')

        self.BG_COLOR = "#0a192f"
        self.FG_COLOR = "#ccd6f6"
        self.LIGHT_BG = "#112240"
        self.ACCENT_COLOR = "#008080"
        self.HIGHLIGHT_COLOR = "#40E0D0"
        self.START_DATE_COLOR = "#2ca3a3"
        self.END_DATE_COLOR = "#1f5f5f"
        self.RANGE_BG_COLOR = "#1a3b5c"

        style.configure('.', background=self.BG_COLOR, foreground=self.FG_COLOR, font=('Segoe UI', 10))
        
        style.configure('TButton', font=('Segoe UI', 10, 'bold'), background=self.ACCENT_COLOR, foreground='white', borderwidth=0, focusthickness=0, padding=8)
        style.map('TButton', background=[('active', '#006666')])

        style.configure("Treeview", rowheight=25, fieldbackground=self.LIGHT_BG, background=self.LIGHT_BG, foreground=self.FG_COLOR)
        style.configure("Treeview.Heading", font=('Segoe UI', 10, 'bold'), background=self.ACCENT_COLOR, foreground='white')
        style.map("Treeview.Heading", background=[('active', self.ACCENT_COLOR)])
        
        style.configure('TEntry',
                        fieldbackground=self.LIGHT_BG,
                        foreground=self.FG_COLOR,
                        insertcolor=self.FG_COLOR)
        style.map('TEntry',
                  fieldbackground=[('disabled', '#0a192f')],
                  foreground=[('disabled', '#6a7b9d')])
        
        style.configure('TCombobox', fieldbackground=self.LIGHT_BG, background=self.LIGHT_BG, arrowcolor=self.FG_COLOR, foreground=self.FG_COLOR, selectbackground=self.LIGHT_BG, selectforeground=self.FG_COLOR)
        
        self.root.option_add('*TCombobox*Listbox.background', self.LIGHT_BG)
        self.root.option_add('*TCombobox*Listbox.foreground', self.FG_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', self.ACCENT_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectForeground', self.FG_COLOR)

        style.configure('TLabelframe', background=self.BG_COLOR, bordercolor=self.ACCENT_COLOR)
        style.configure('TLabelframe.Label', foreground=self.HIGHLIGHT_COLOR, background=self.BG_COLOR, font=('Segoe UI', 9, 'bold'))

        # Estilos para o calendário
        style.configure('DateRange.TLabel', background=self.RANGE_BG_COLOR, foreground=self.FG_COLOR)
        style.configure('StartDate.TLabel', background=self.START_DATE_COLOR, foreground='white', font=('Segoe UI', 10, 'bold'))
        style.configure('EndDate.TLabel', background=self.END_DATE_COLOR, foreground='white', font=('Segoe UI', 10, 'bold'))

    def setup_ui(self):
        main_frame = tk.Frame(self.root, bg="#0a192f")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        main_frame.grid_rowconfigure(2, weight=4, minsize=int(self.root.winfo_screenheight() * 0.3)) 
        main_frame.grid_rowconfigure(1, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        top_frame = tk.Frame(main_frame, bg="#0a192f")
        top_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        header_frame = tk.Frame(top_frame, bg="#0a192f")
        header_frame.pack(fill=tk.X)
        
        try:
            logo_img = Image.open(LOGO_PATH)
            logo_img = logo_img.resize((45, 45), Image.Resampling.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(logo_img)
            logo_label = tk.Label(header_frame, image=self.logo_photo, bg="#0a192f")
            logo_label.pack(side=tk.LEFT, padx=(0, 10))
        except FileNotFoundError:
            print(f"AVISO: Arquivo da logo não encontrado em '{LOGO_PATH}'.")
        except Exception as e:
            print(f"ERRO ao carregar a logo: {e}")

        app_title = tk.Label(header_frame, text="WN Ponto Certo", font=("Segoe UI", 20, "bold"), fg="white", bg="#0a192f")
        app_title.pack(side=tk.LEFT)

        actions_frame = tk.Frame(top_frame, bg="#0a192f")
        actions_frame.pack(fill=tk.X, pady=(10,0))
        
        ttk.Button(actions_frame, text="📂 Importar Dados", command=self.on_import, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="💰 Pagamento de Saldo", command=self.on_extra_payment, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="📄 Exportar Log", command=self.on_export_log, style='TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(actions_frame, text="🚪 Sair", command=self.root.quit, style='TButton').pack(side=tk.RIGHT)

        log_frame = ttk.LabelFrame(main_frame, text=" Área de Log ", style='TLabelframe')
        log_frame.grid(row=1, column=0, sticky="nsew", pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, height=5, bg="#112240", fg="#a8b2d1", insertbackground="white", font=("Consolas", 9), relief=tk.FLAT, borderwidth=5)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        self.setup_point_viewer(main_frame)
        
    def on_import(self):
        filepath = filedialog.askopenfilename(title="Selecione o arquivo TXT", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not filepath: return
        try:
            self.append_log(f"Arquivo selecionado: {filepath}")
            self.append_log("Iniciando importação e processamento...")
            import_glog_txt(filepath, self.db, logger=self.append_log)
            self.append_log("Processamento concluído ✅")
            self.update_employee_filter()
            self.load_point_viewer(force_reload=True)
        except Exception as e:
            self.append_log(f"Erro na importação: {e}")
            messagebox.showerror("Erro", str(e))
        
    def on_extra_payment(self):
        win = tk.Toplevel(self.root)
        win.title("Pagamento de Saldos")
        win.geometry("600x350")
        win.configure(bg="#0a192f")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        FG_COLOR = "#ccd6f6"
        BG_COLOR = "#0a192f"

        frame_form = tk.Frame(win, bg=BG_COLOR)
        frame_form.pack(padx=20, pady=20, fill="both", expand=True)
        tk.Label(frame_form, text="1. Selecione o Funcionário:", bg=BG_COLOR, fg=FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))
        
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]
        cmb_func = ttk.Combobox(frame_form, values=nomes, state="readonly", width=50)
        cmb_func.pack(anchor="w")

        frame_details = tk.Frame(frame_form, bg=BG_COLOR)
        frame_extras = ttk.LabelFrame(frame_details, text=" Pagamento de Extras ", style='TLabelframe')
        frame_bh = ttk.LabelFrame(frame_details, text=" Pagamento de Banco de Horas ", style='TLabelframe')
        
        lbl_extras_saldo = tk.Label(frame_extras, bg=BG_COLOR, fg=FG_COLOR, font=("Segoe UI", 10))
        cmb_extras_choice = ttk.Combobox(frame_extras, values=["Não", "Sim"], state="readonly", width=5)
        entry_extras_qty = ttk.Entry(frame_extras, width=10, state="disabled")
        
        lbl_bh_saldo = tk.Label(frame_bh, bg=BG_COLOR, fg=FG_COLOR, font=("Segoe UI", 10))
        cmb_bh_choice = ttk.Combobox(frame_bh, values=["Não", "Sim"], state="readonly", width=5)
        entry_bh_qty = ttk.Entry(frame_bh, width=10, state="disabled")
        
        btn_salvar = ttk.Button(frame_form, text="✅ Salvar e Deduzir Saldos", width=30, style='TButton', state="disabled")

        def toggle_entry(entry, choice_cmb): entry.config(state="normal" if choice_cmb.get() == "Sim" else "disabled")
        cmb_extras_choice.bind("<<ComboboxSelected>>", lambda e: toggle_entry(entry_extras_qty, cmb_extras_choice))
        cmb_bh_choice.bind("<<ComboboxSelected>>", lambda e: toggle_entry(entry_bh_qty, cmb_bh_choice))

        def update_ui(event=None):
            selection = cmb_func.get()
            if not selection: return
            matricula = selection.split(" - ")[0]
            func_info = self.db.get_funcionario_info(matricula)
            
            lbl_extras_saldo.config(text=f"Saldo Atual: {int(func_info.get('extras_disponiveis', 0))} un.")
            lbl_bh_saldo.config(text=f"Saldo Atual: {format_minutes_to_hms(func_info.get('banco_horas', 0))}")
            
            cmb_extras_choice.set("Não"); cmb_bh_choice.set("Não")
            entry_extras_qty.delete(0, 'end'); entry_bh_qty.delete(0, 'end')
            toggle_entry(entry_extras_qty, cmb_extras_choice); toggle_entry(entry_bh_qty, cmb_bh_choice)
            
            frame_details.pack(pady=20, fill="x")
            frame_extras.pack(fill="x", pady=5); frame_bh.pack(fill="x", pady=5)
            btn_salvar.pack(pady=20); btn_salvar.config(state="normal")
            
        cmb_func.bind("<<ComboboxSelected>>", update_ui)

        def save_changes():
            selection = cmb_func.get()
            if not selection: messagebox.showerror("Erro", "Nenhum funcionário selecionado.", parent=win); return
            matricula = selection.split(" - ")[0]
            # func_info removido
            unidades_a_deduzir, minutos_a_deduzir = 0, 0
            if cmb_extras_choice.get() == "Sim":
                try: 
                    unidades_a_deduzir = int(entry_extras_qty.get())
                    # Validação removida
                except: 
                    messagebox.showerror("Erro", "Quantidade de extras deve ser um número inteiro.", parent=win)
                    return
            if cmb_bh_choice.get() == "Sim":
                bh_str = entry_bh_qty.get()
                if not re.match(r'^-?\d{1,3}:\d{2}:\d{2}$', bh_str): messagebox.showerror("Erro", "Formato do BH deve ser hh:mm:ss.", parent=win); return
                try:
                    sign = -1 if bh_str.startswith('-') else 1
                    h, m, s = map(int, bh_str.replace('-', '').split(':'))
                    minutos_a_deduzir = (h * 60 + m + s / 60) * sign
                except: messagebox.showerror("Erro", "Valor de BH inválido.", parent=win); return
            
            if unidades_a_deduzir == 0 and minutos_a_deduzir == 0:
                messagebox.showinfo("Aviso", "Nenhuma alteração a ser salva.", parent=win); return
            
            confirm_msg = f"Deseja deduzir {unidades_a_deduzir} extra(s) e {format_minutes_to_hms(minutos_a_deduzir)} do saldo de {selection.split(' - ')[1]}?"
            # Verifica se o saldo ficaria negativo (não impede, apenas avisa)
            func_info_atual = self.db.get_funcionario_info(matricula)
            if unidades_a_deduzir > func_info_atual.get('extras_disponiveis', 0):
                 confirm_msg += "\n\nAVISO: O saldo de extras ficará negativo."
            
            if messagebox.askyesno("Confirmar", confirm_msg, parent=win):
                if self.db.update_saldos(matricula, minutos_a_deduzir, unidades_a_deduzir):
                    messagebox.showinfo("Sucesso", "Saldos atualizados!", parent=win)
                    self.load_point_viewer(force_reload=True)
                    win.destroy()
                else: messagebox.showerror("Erro", "Não foi possível salvar.", parent=win)

        btn_salvar.config(command=save_changes)
        
        lbl_extras_saldo.grid(row=0, column=0, sticky="w", padx=5)
        tk.Label(frame_extras, text="Pagar?", bg=BG_COLOR, fg=FG_COLOR).grid(row=0, column=1, sticky="w", padx=10); cmb_extras_choice.grid(row=0, column=2, padx=5)
        tk.Label(frame_extras, text="Qtde (un):", bg=BG_COLOR, fg=FG_COLOR).grid(row=0, column=3, sticky="w", padx=10); entry_extras_qty.grid(row=0, column=4, padx=5)
        lbl_bh_saldo.grid(row=0, column=0, sticky="w", padx=5)
        tk.Label(frame_bh, text="Pagar?", bg=BG_COLOR, fg=FG_COLOR).grid(row=0, column=1, sticky="w", padx=10); cmb_bh_choice.grid(row=0, column=2, padx=5)
        tk.Label(frame_bh, text="Qtde (hh:mm:ss):", bg=BG_COLOR, fg=FG_COLOR).grid(row=0, column=3, sticky="w", padx=10); entry_bh_qty.grid(row=0, column=4, padx=5)

    def on_export_log(self):
        win = tk.Toplevel(self.root)
        win.title("Exportar Log de Edições")
        win.geometry("700x350")
        win.configure(bg="#0a192f")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        FG_COLOR = "#ccd6f6"
        BG_COLOR = "#0a192f"

        main_frame = tk.Frame(win, bg=BG_COLOR, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text="1. Selecione o Funcionário:", bg=BG_COLOR, fg=FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))
        nomes = [f"{f['matricula']} - {f['nome']}" for f in self.db.get_all_funcionarios()]
        cmb_func = ttk.Combobox(main_frame, values=nomes, state="readonly", width=50)
        cmb_func.pack(anchor="w", pady=(0, 20))

        tk.Label(main_frame, text="2. Selecione o Período:", bg=BG_COLOR, fg=FG_COLOR, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 5))
        period_frame = tk.Frame(main_frame, bg=BG_COLOR)
        period_frame.pack(anchor="w")

        tk.Label(period_frame, text="De:", bg=BG_COLOR, fg=FG_COLOR).pack(side=tk.LEFT, padx=(0,5))
        cal_start = Calendar(period_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080")
        cal_start.pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Label(period_frame, text="Até:", bg=BG_COLOR, fg=FG_COLOR).pack(side=tk.LEFT, padx=(0,5))
        cal_end = Calendar(period_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR', background="#008080", foreground="white", headersbackground="#008080")
        cal_end.pack(side=tk.LEFT)

        btn_export = ttk.Button(main_frame, text="Gerar PDF", style='TButton')
        btn_export.pack(pady=20)

        def generate_pdf():
            selection = cmb_func.get()
            if not selection:
                messagebox.showerror("Erro", "Nenhum funcionário selecionado.", parent=win)
                return
            
            matricula = selection.split(" - ")[0]
            nome_func = " ".join(selection.split(" - ")[1:])
            start_date = cal_start.get_date()
            end_date = cal_end.get_date()

            logs = self.db.get_logs_for_period(matricula, start_date, end_date)

            if not logs:
                messagebox.showinfo("Aviso", "Nenhum registro de log encontrado para o funcionário e período selecionados.", parent=win)
                return

            filepath = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("PDF files", "*.pdf")],
                title="Salvar Relatório de Log",
                initialfile=f"Log_{nome_func.replace(' ','_')}_{start_date}_a_{end_date}.pdf"
            )

            if not filepath:
                return

            try:
                doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
                styles = getSampleStyleSheet()
                story = []

                story.append(Paragraph("Relatório de Log de Alterações", styles['h1']))
                story.append(Spacer(1, 0.5*cm))
                
                story.append(Paragraph(f"<b>Funcionário:</b> {nome_func}", styles['Normal']))
                story.append(Paragraph(f"<b>Matrícula:</b> {matricula}", styles['Normal']))
                story.append(Paragraph(f"<b>Período:</b> {datetime.strptime(start_date, '%Y-%m-%d').strftime('%d/%m/%Y')} a {datetime.strptime(end_date, '%Y-%m-%d').strftime('%d/%m/%Y')}", styles['Normal']))
                story.append(Spacer(1, 1*cm))

                table_data = [['Data do Ponto', 'Data da Edição', 'Valor Antigo', 'Valor Novo', 'Justificativa']]
                for log in logs:
                    data_ponto_fmt = datetime.strptime(log['data_ponto'], '%Y-%m-%d').strftime('%d/%m/%Y')
                    data_edicao_fmt = datetime.strptime(log['data_edicao'], '%Y-%m-%d %H:%M:%S').strftime('%d/%m/%Y %H:%M')
                    table_data.append([data_ponto_fmt, data_edicao_fmt, log['periodos_antigos'], log['periodos_novos'], log['justificativa']])

                t = Table(table_data, colWidths=[2.5*cm, 3*cm, 3*cm, 3*cm, 5*cm])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.teal),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0,0), (-1,0), 12),
                    ('BACKGROUND', (0,1), (-1,-1), colors.beige),
                    ('GRID', (0,0), (-1,-1), 1, colors.black)
                ]))
                story.append(t)
                
                doc.build(story)
                messagebox.showinfo("Sucesso", f"Relatório salvo com sucesso em:\n{filepath}", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Erro ao Gerar PDF", f"Ocorreu um erro: {e}", parent=win)

        btn_export.config(command=generate_pdf)

    def setup_point_viewer(self, parent_frame):
        frame_viewer = ttk.LabelFrame(parent_frame, text=" Panorama de Pontos ", style='TLabelframe')
        frame_viewer.grid(row=2, column=0, sticky="nsew", pady=5)
        # Configuração das linhas e colunas internas do frame_viewer
        frame_viewer.grid_rowconfigure(3, weight=1) # Linha da tabela (agora é 3)
        frame_viewer.grid_columnconfigure(0, weight=1) # Coluna única

        # --- Frame de Controles (Funcionário, Calendário, Botões) ---
        frame_controls = tk.Frame(frame_viewer, bg="#0a192f")
        frame_controls.grid(row=0, column=0, sticky="ew", pady=(5,0), padx=10)

        # Funcionário
        tk.Label(frame_controls, text="Funcionário:", bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(0,5))
        self.cmb_filter_func = ttk.Combobox(frame_controls, state="readonly", width=40)
        self.cmb_filter_func.pack(side=tk.LEFT, padx=(0, 20))
        self.cmb_filter_func.bind("<<ComboboxSelected>>", lambda e: self.load_point_viewer(force_reload=True))

        # Botões da Tabela
        action_button_frame = tk.Frame(frame_controls, bg="#0a192f")
        action_button_frame.pack(side=tk.RIGHT)
        ttk.Button(action_button_frame, text="Atualizar Tabela", command=self.load_point_viewer).pack(side=tk.LEFT, padx=5)
        ttk.Button(action_button_frame, text="💾 Salvar Alterações", command=self.commit_all_changes).pack(side=tk.LEFT, padx=5)
        
        # --- Frame do Calendário e Labels de Data ---
        calendar_frame = tk.Frame(frame_viewer, bg="#0a192f")
        calendar_frame.grid(row=1, column=0, sticky="ew", pady=5, padx=10)

        self.main_calendar = Calendar(calendar_frame, selectmode="day", date_pattern="yyyy-mm-dd", locale='pt_BR',
                                      background="#008080", foreground="white", headersbackground="#008080",
                                      normalbackground="#112240", weekendbackground="#172a45", # Cores de fundo dos dias
                                      othermonthbackground="#0a192f", othermonthforeground="#6a7b9d", # Cor de outros meses
                                      selectbackground=self.ACCENT_COLOR, # Cor do dia selecionado no clique
                                      )
        self.main_calendar.pack(side=tk.LEFT, padx=(0, 20))
        self.main_calendar.bind("<<CalendarSelected>>", self.on_calendar_click)

        # Configura as tags de estilo para o calendário
        self.main_calendar.tag_config('start_date', background=self.START_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('end_date', background=self.END_DATE_COLOR, foreground='white')
        self.main_calendar.tag_config('range_date', background=self.RANGE_BG_COLOR, foreground='#ccd6f6') 

        # Frame para os labels de data selecionada
        date_labels_frame = tk.Frame(calendar_frame, bg="#0a192f")
        date_labels_frame.pack(side=tk.LEFT, anchor='n')

        tk.Label(date_labels_frame, text="Período Selecionado:", bg="#0a192f", fg="#ccd6f6", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        
        start_frame = tk.Frame(date_labels_frame, bg="#0a192f")
        start_frame.pack(anchor='w', pady=2)
        tk.Label(start_frame, text="Início:", bg="#0a192f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_start = tk.Label(start_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_start.pack(side=tk.LEFT)

        end_frame = tk.Frame(date_labels_frame, bg="#0a192f")
        end_frame.pack(anchor='w', pady=2)
        tk.Label(end_frame, text="Fim:", bg="#0a192f", fg="#ccd6f6", width=5, anchor='w').pack(side=tk.LEFT)
        self.lbl_selected_end = tk.Label(end_frame, text="--/--/----", bg="#0a192f", fg="white", font=('Segoe UI', 10, 'bold'), width=12, anchor='w')
        self.lbl_selected_end.pack(side=tk.LEFT)


        # --- Frame de Saldos ---
        frame_saldos = ttk.LabelFrame(frame_viewer, text=" Saldos Atuais do Funcionário Selecionado ", style='TLabelframe')
        frame_saldos.grid(row=2, column=0, sticky="ew", pady=(10, 5), padx=10)
        
        tk.Label(frame_saldos, text="Banco de Horas:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT, padx=(10,0))
        self.lbl_saldo_bh_total = tk.Label(frame_saldos, text="--:--:--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=15, anchor="w")
        self.lbl_saldo_bh_total.pack(side=tk.LEFT, padx=(5, 20))
        
        tk.Label(frame_saldos, text="Extras Disponíveis:", font=("Segoe UI", 11), bg="#0a192f", fg="white").pack(side=tk.LEFT)
        self.lbl_saldo_extras_total = tk.Label(frame_saldos, text="--", font=("Segoe UI", 11, "bold"), bg="#0a192f", fg="white", width=10, anchor="w")
        self.lbl_saldo_extras_total.pack(side=tk.LEFT, padx=5)

        # --- Frame da Tabela ---
        tree_frame = tk.Frame(frame_viewer, bg="#0a192f")
        tree_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        columns = ("Matrícula", "Nome", "Data", "E1", "S1", "E2", "S2", "Carga_Horaria", "Total_Desconto")
        self.tree_viewer = ttk.Treeview(tree_frame, columns=columns, show="headings")
        
        v_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree_viewer.yview)
        h_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree_viewer.xview)
        self.tree_viewer.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
        
        self.tree_viewer.grid(row=0, column=0, sticky='nsew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        h_scroll.grid(row=1, column=0, sticky='ew')
        
        col_widths = {"Matrícula": 80, "Nome": 200, "Data": 100, "E1": 70, "S1": 70, "E2": 70, "S2": 70, "Carga_Horaria": 120, "Total_Desconto": 120}
        
        for col in columns:
            self.tree_viewer.heading(col, text=col.replace('_', ' ').replace('Carga Horaria', 'Carga Horária'))
            self.tree_viewer.column(col, width=col_widths.get(col, 100), anchor=tk.CENTER, stretch=tk.NO)
            
        self.tree_viewer.bind('<ButtonRelease-1>', self.start_in_place_edit)
        
        self.tree_viewer.tag_configure('evenrow', background='#112240')
        self.tree_viewer.tag_configure('oddrow', background='#172a45')

        self.update_employee_filter()
        # Define as datas iniciais e atualiza o calendário e a tabela
        self._update_calendar_tags()
        self.load_point_viewer(force_reload=True)

    # -----------------------------------------------------------------
    # INÍCIO DA CORREÇÃO DO BUG
    # -----------------------------------------------------------------

    def _clear_calendar_tags(self):
        """Remove todas as tags de data do calendário principal."""
        # CORREÇÃO: Usa 'calevent_remove' da tkcalendar, não 'event_remove' do Tkinter
        # O 'all' remove todos os eventos de todas as tags
        self.main_calendar.calevent_remove('all')

    def _update_calendar_tags(self):
        """Atualiza as tags visuais no calendário com base nas datas selecionadas."""
        self._clear_calendar_tags()
        if self.selected_start_date:
            # CORREÇÃO: Usa 'calevent_create' da tkcalendar com o argumento 'tags'
            self.main_calendar.calevent_create(self.selected_start_date, 'Início', tags='start_date')
            self.lbl_selected_start.config(text=self.selected_start_date.strftime("%d/%m/%Y"))
        else:
            self.lbl_selected_start.config(text="--/--/----")

        if self.selected_end_date:
            # CORREÇÃO: Usa 'calevent_create' da tkcalendar com o argumento 'tags'
            self.main_calendar.calevent_create(self.selected_end_date, 'Fim', tags='end_date')
            self.lbl_selected_end.config(text=self.selected_end_date.strftime("%d/%m/%Y"))
            
            # Marca o intervalo entre as datas (se houver e for válido)
            if self.selected_start_date and self.selected_start_date < self.selected_end_date:
                current_date = self.selected_start_date + timedelta(days=1)
                while current_date < self.selected_end_date:
                    # CORREÇÃO: Usa 'calevent_create' da tkcalendar com o argumento 'tags'
                    # (Não precisa de texto no meio do intervalo, apenas a tag de cor)
                    self.main_calendar.calevent_create(current_date, '', tags='range_date')
                    current_date += timedelta(days=1)
        else:
             self.lbl_selected_end.config(text="--/--/----")

    # -----------------------------------------------------------------
    # FIM DA CORREÇÃO DO BUG
    # -----------------------------------------------------------------


    def on_calendar_click(self, event=None):
        """Gerencia a seleção de datas de início e fim no calendário único."""
        clicked_date = self.main_calendar.selection_get()
        if not clicked_date: return

        if self.selecting_start:
            self.selected_start_date = clicked_date
            self.selected_end_date = None # Reseta a data final
            self.selecting_start = False
            self._update_calendar_tags() # Atualiza visualmente
            self.lbl_selected_end.config(text="Selecione...") # Indica próxima ação
        else:
            self.selected_end_date = clicked_date
            # Garante que start <= end
            if self.selected_start_date and self.selected_end_date < self.selected_start_date:
                self.selected_start_date, self.selected_end_date = self.selected_end_date, self.selected_start_date
            
            self.selecting_start = True # Próximo clique será para o início novamente
            self._update_calendar_tags() # Atualiza visualmente
            self.load_point_viewer(force_reload=True) # Carrega dados para o novo intervalo

    def update_employee_filter(self):
        funcionarios = self.db.get_all_funcionarios()
        nomes = ["Todos"] + [f"{f['matricula']} - {f['nome']}" for f in funcionarios]
        self.cmb_filter_func['values'] = nomes
        self.cmb_filter_func.set("Todos")

    def load_point_viewer(self, force_reload=False):
        if self.unsaved_edits and not force_reload:
            if not messagebox.askyesno("Atualizar Tabela", "Você possui alterações não salvas que serão perdidas.\nDeseja continuar e descartar as alterações?"):
                return
            self.unsaved_edits = {}

        # << CALENDÁRIO ÚNICO: Usa as datas armazenadas >>
        start_date = self.selected_start_date
        end_date = self.selected_end_date

        # Se alguma data não foi selecionada, não carrega nada (ou usa um default)
        if not start_date or not end_date:
             for i in self.tree_viewer.get_children(): self.tree_viewer.delete(i) # Limpa tabela
             self.lbl_saldo_bh_total.config(text="--:--:--") # Limpa saldos
             self.lbl_saldo_extras_total.config(text="--")
             return

        selected_func = self.cmb_filter_func.get()
        target_matricula = selected_func.split(" - ")[0] if selected_func != "Todos" else None
        
        for i in self.tree_viewer.get_children(): self.tree_viewer.delete(i)
        
        # Passa os objetos date diretamente para get_point_panorama
        panorama_data = self.db.get_point_panorama(start_date, end_date, target_matricula)
        
        for i, item in enumerate(panorama_data):
            # A data já vem no formato YYYY-MM-DD do DB ou cálculo
            data_db_str = item['Data']
            try:
                data_ptbr = datetime.strptime(data_db_str, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                 data_ptbr = data_db_str # Mantém como está se o formato for inválido

            values = (item['Matricula'], item['Nome'], data_ptbr, item['E1'], item['S1'], item['E2'], item['S2'], item['Carga_Horaria'], item['Total_Desconto'])
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.tree_viewer.insert("", "end", values=values, iid=(item['Matricula'], item['Data']), tags=(tag,))
            
        # Atualiza saldos totais
        if target_matricula:
            func_info = self.db.get_funcionario_info(target_matricula)
            saldo_bh = func_info.get('banco_horas', 0)
            saldo_extras = func_info.get('extras_disponiveis', 0)
            self.lbl_saldo_bh_total.config(text=format_minutes_to_hms(saldo_bh))
            self.lbl_saldo_extras_total.config(text=str(int(saldo_extras)))
        else:
            self.lbl_saldo_bh_total.config(text="--:--:--")
            self.lbl_saldo_extras_total.config(text="--")
            
    def append_log(self, text):
        if hasattr(self, 'log_area'):
            self.log_area.insert(tk.END, f"{datetime.now().strftime('%H:%M:%S')} - {text}\n")
            self.log_area.see(tk.END)
        else:
            print(text)

    def start_in_place_edit(self, event):
        if self.editing_widgets:
            if 'entry' in self.editing_widgets: self.editing_widgets['entry'].destroy()
            if 'cmb' in self.editing_widgets: self.editing_widgets['cmb'].destroy()
            self.editing_widgets = {}

        item_id = self.tree_viewer.identify_row(event.y)
        if not item_id: return

        column_id = self.tree_viewer.identify_column(event.x)
        try:
            col_index = int(column_id.replace('#', '')) - 1 
            column_name = self.tree_viewer.heading(column_id, 'text')
        except (ValueError, IndexError):
            self.append_log(f"Erro na edição: Não foi possível identificar a coluna clicada.")
            return

        editable_columns = ["E1", "S1", "E2", "S2"]
        if column_name not in editable_columns: return 
        
        x, y, width, height = self.tree_viewer.bbox(item_id, column_id)
        values = self.tree_viewer.item(item_id, 'values')
        matricula, data_ptbr, current_time = values[0], values[2], values[col_index]
        data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        
        entry_edit = ttk.Entry(self.tree_viewer)
        entry_edit.place(x=x, y=y, width=width, height=height)
        
        entry_edit.insert(0, current_time if current_time not in ('', 'N/A') else '')
        entry_edit.focus()
        
        justificativa_cmb = ttk.Combobox(self.tree_viewer, values=LISTA_JUSTIFICATIVAS, state="readonly", width=30)
        justificativa_cmb.place(x=x + width + 5, y=y, height=height)
        edit_key = (matricula, data_db)
        justificativa_cmb.set(self.unsaved_edits.get(edit_key, {}).get('justificativa', LISTA_JUSTIFICATIVAS[0]))
        
        self.editing_widgets = {'entry': entry_edit, 'cmb': justificativa_cmb}
        
        def on_escape(e=None):
            if self.editing_widgets:
                if 'entry' in self.editing_widgets: self.editing_widgets['entry'].destroy()
                if 'cmb' in self.editing_widgets: self.editing_widgets['cmb'].destroy()
                self.editing_widgets.clear()

        def handle_edit(from_cmb=False):
            if not self.editing_widgets: return
            entry = self.editing_widgets.get('entry')
            cmb = self.editing_widgets.get('cmb')
            if not entry or not cmb: return

            new_time, just = entry.get().strip(), cmb.get()
            
            if not (re.match(r'^\d{2}:\d{2}$', new_time) or new_time in ('', 'N/A', '00:00')):
                if new_time != current_time:
                    messagebox.showerror("Erro de Formato", "O formato da hora deve ser HH:MM (ex: 08:30).", parent=self.root)
                on_escape()
                return
            
            temp_vals = list(self.tree_viewer.item(item_id, 'values'))
            temp_vals[col_index] = new_time
            self.tree_viewer.item(item_id, values=tuple(temp_vals))
            
            if edit_key not in self.unsaved_edits:
                self.unsaved_edits[edit_key] = {'E1': temp_vals[3], 'S1': temp_vals[4], 'E2': temp_vals[5], 'S2': temp_vals[6]}
            
            self.unsaved_edits[edit_key][column_name] = new_time
            self.unsaved_edits[edit_key]['justificativa'] = just
            
            self.update_visual_work_hours(item_id)
            if from_cmb:
                on_escape()

        entry_edit.bind('<Return>', lambda e: handle_edit(from_cmb=True))
        entry_edit.bind('<Escape>', on_escape)
        entry_edit.bind('<FocusOut>', lambda e: on_escape())
        
        justificativa_cmb.bind('<<ComboboxSelected>>', lambda e: handle_edit(from_cmb=True))
        justificativa_cmb.bind('<Escape>', on_escape)

    def update_visual_work_hours(self, item_id):
        values = self.tree_viewer.item(item_id, 'values')
        data_ptbr = values[2]
        data_db = datetime.strptime(data_ptbr, "%d/%m/%Y").strftime("%Y-%m-%d")
        all_times_raw = [values[3], values[4], values[5], values[6]]
        
        minutos_totais = 0
        for i in range(0, 4, 2):
            e_time, s_time = all_times_raw[i], all_times_raw[i+1]
            if e_time and s_time and e_time not in ('N/A', '00:00', '') and s_time not in ('N/A', '00:00', ''):
                try:
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M")
                    saida = datetime.strptime(f"{data_db} {s_time}", "%Y-%m-%d %H:%M")
                    if saida < entrada: saida += timedelta(days=1)
                    
                    turno = "Manhã" if i == 0 else "Tarde"
                    jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                    
                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                    deduction_min = calculate_deduction(late_min)
                    bruto_min = (saida - entrada).total_seconds() / 60
                    liquido_min = max(0, bruto_min - deduction_min)
                    minutos_totais += liquido_min
                except ValueError:
                    continue
        
        new_values = list(values)
        new_values[7] = format_minutes_to_hms(minutos_totais)
        self.tree_viewer.item(item_id, values=tuple(new_values))

    def process_manual_update_and_save(self, matricula, data_db, all_times_raw, justificativa):
        periodos, minutos_totais = [], 0
        for i in range(0, 4, 2):
            e_time, s_time = all_times_raw[i], all_times_raw[i+1]
            if e_time and s_time and e_time not in ('N/A', '00:00', '') and s_time not in ('N/A', '00:00', ''):
                try:
                    entrada = datetime.strptime(f"{data_db} {e_time}", "%Y-%m-%d %H:%M")
                    saida = datetime.strptime(f"{data_db} {s_time}", "%Y-%m-%d %H:%M")
                    if saida < entrada: saida += timedelta(days=1)

                    turno = "Manhã" if i == 0 else "Tarde"
                    jornada_inicio = datetime.strptime(f"{data_db} {'07:30' if turno == 'Manhã' else '13:00'}", "%Y-%m-%d %H:%M")
                    
                    late_min = max(0, (entrada - jornada_inicio).total_seconds() / 60)
                    deduction_min = calculate_deduction(late_min)
                    bruto_min = (saida - entrada).total_seconds() / 60
                    liquido_min = max(0, bruto_min - deduction_min)
                    minutos_totais += liquido_min
                    
                    periodos.append({
                        "entrada": str(entrada), "saida": str(saida), 
                        "minutos_brutos": format_minutes_to_hms(bruto_min), 
                        "deducao_minutos": format_minutes_to_hms(deduction_min), 
                        "minutos_liquidos": format_minutes_to_hms(liquido_min)
                    })
                except ValueError:
                    self.append_log(f"ERRO de formato em '{e_time}' ou '{s_time}'. Período ignorado.")
                    continue
        
        self.db.insert_horas_trabalhadas({
            "matricula": matricula, "data": data_db, 
            "minutos_totais": format_minutes_to_hms(minutos_totais), 
            "periodos": periodos
        }, justificativa=justificativa)
        
        self.append_log(f"Ponto de {matricula} em {data_db} atualizado. Justificativa: '{justificativa}'.")

    def commit_all_changes(self):
        if self.editing_widgets:
            if 'entry' in self.editing_widgets:
                self.editing_widgets['entry'].event_generate('<FocusOut>')
        
        if not self.unsaved_edits:
            messagebox.showinfo("Salvar", "Nenhuma alteração pendente para salvar."); return
        
        if not messagebox.askyesno("Confirmar Alterações", f"Você tem {len(self.unsaved_edits)} dia(s) com alterações pendentes.\nDeseja salvar tudo e recalcular os saldos dos funcionários afetados?"):
            return

        self.append_log(f"Iniciando salvamento de {len(self.unsaved_edits)} alterações pendentes...")
        affected_employees = set()
        for (matricula, data_db), edits in self.unsaved_edits.items():
            affected_employees.add(matricula)
            justificativa = edits.get('justificativa', 'Ajuste Manual sem Justificativa')
            self.process_manual_update_and_save(matricula, data_db, [edits['E1'], edits['S1'], edits['E2'], edits['S2']], justificativa)
        
        self.append_log("Recalculando saldos para funcionários afetados...")
        for matricula in affected_employees:
            self.db.recalculate_full_balance_for_employee(matricula)
        
        self.unsaved_edits = {}
        messagebox.showinfo("Sucesso", "Todas as alterações foram salvas e os saldos recalculados.")
        self.load_point_viewer(force_reload=True)

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()