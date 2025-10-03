import os
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk
from collections import defaultdict
from datetime import datetime, timedelta
import sqlite3
import json
from pathlib import Path
from tkcalendar import Calendar
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
import pandas as pd

# -------------------------
# BANCO DE DADOS (SQLite)
# -------------------------
DEFAULT_DB = Path(__file__).parent.joinpath("ponto.db")

class DatabaseManager:
    """Gerencia a conexão e as operações com o banco de dados SQLite."""
    def __init__(self, db_path=None):
        self.db_path = str(db_path if db_path else DEFAULT_DB)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_database()

    def create_database(self):
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS funcionarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula TEXT UNIQUE,
                nome TEXT,
                salario REAL DEFAULT 0,
                banco_horas REAL DEFAULT 0,
                extras_disponiveis REAL DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS horas_trabalhadas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula TEXT,
                data TEXT,
                minutos_totais REAL,
                periodos TEXT,
                criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS recibos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matricula TEXT,
                data_emissao TEXT,
                periodo_inicio TEXT,
                periodo_fim TEXT,
                valor_pago REAL
            )
        """)
        self.conn.commit()

    def insert_funcionario(self, dados):
        try:
            self.conn.execute("INSERT OR IGNORE INTO funcionarios (matricula, nome) VALUES (?, ?)", (dados.get("matricula"), dados.get("nome")))
            self.conn.commit()
        except Exception as e:
            print("Erro insert_funcionario:", e)

    def insert_horas_trabalhadas(self, dados):
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO horas_trabalhadas (matricula, data, minutos_totais, periodos)
                VALUES (?, ?, ?, ?)
            """, (dados.get("matricula"), dados.get("data"), dados.get("minutos_totais"), json.dumps(dados.get("periodos"), default=str)))
            self.conn.commit()
        except Exception as e:
            print("Erro insert_horas_trabalhadas:", e)

    def update_banco_horas(self, matricula, minutos_adicionais):
        try:
            c = self.conn.cursor()
            c.execute("UPDATE funcionarios SET banco_horas = banco_horas + ? WHERE matricula = ?", (minutos_adicionais, matricula))
            self.conn.commit()
            
            funcionario = self.get_funcionario_info(matricula)
            if funcionario:
                banco_horas_atual = funcionario['banco_horas']
                if banco_horas_atual >= 240:
                    num_extras = int(banco_horas_atual / 240)
                    self.update_banco_horas(matricula, -num_extras * 240)
                    self.update_extras_disponiveis(matricula, num_extras * 240)
        except Exception as e:
            print(f"Erro ao atualizar banco de horas: {e}")

    def update_extras_disponiveis(self, matricula, minutos_adicionais):
        try:
            c = self.conn.cursor()
            c.execute("UPDATE funcionarios SET extras_disponiveis = extras_disponiveis + ? WHERE matricula = ?", (minutos_adicionais, matricula))
            self.conn.commit()
        except Exception as e:
            print(f"Erro ao atualizar extras disponíveis: {e}")

    def get_funcionario_info(self, matricula):
        c = self.conn.cursor()
        c.execute("SELECT matricula, nome, salario, banco_horas, extras_disponiveis FROM funcionarios WHERE matricula = ?", (matricula,))
        return dict(c.fetchone() or {})
    
    def get_all_funcionarios(self):
        c = self.conn.cursor()
        c.execute("SELECT matricula, nome FROM funcionarios ORDER BY nome")
        return [dict(row) for row in c.fetchall()]

    def get_horas_trabalhadas_periodo(self, matricula, start_date, end_date):
        c = self.conn.cursor()
        c.execute("""
            SELECT minutos_totais FROM horas_trabalhadas 
            WHERE matricula = ? AND data BETWEEN ? AND ?
        """, (matricula, start_date, end_date))
        return [row['minutos_totais'] for row in c.fetchall()]

    def update_salario(self, matricula, salario):
        try:
            self.conn.execute("UPDATE funcionarios SET salario = ? WHERE matricula = ?", (salario, matricula))
            self.conn.commit()
        except Exception as e:
            print("Erro ao atualizar salário:", e)

    def insert_recibo(self, dados):
        try:
            self.conn.execute("""
                INSERT INTO recibos (matricula, data_emissao, periodo_inicio, periodo_fim, valor_pago)
                VALUES (?, ?, ?, ?, ?)
            """, (dados['matricula'], dados['data_emissao'], dados['periodo_inicio'], dados['periodo_fim'], dados['valor_pago']))
            self.conn.commit()
        except Exception as e:
            print("Erro ao inserir recibo:", e)

# -------------------------
# FUNÇÕES DE APOIO E LÓGICA DE NEGÓCIO
# -------------------------
def try_parse_datetime(s):
    for fmt in ["%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"]:
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, IndexError):
            pass
    return None

def calculate_deduction(minutes_late):
    if minutes_late <= 5:
        return 0
    elif minutes_late <= 10:
        return minutes_late * 2
    elif minutes_late <= 15:
        return minutes_late * 3
    else:
        return minutes_late

def format_minutes_to_hms(minutes):
    if minutes is None:
        return "00:00:00"
    minutes = max(0, minutes)
    hours = int(minutes // 60)
    remaining_minutes = int(minutes % 60)
    seconds = int((minutes * 60) % 60)
    return f"{hours:02}:{remaining_minutes:02}:{seconds:02}"

def import_glog_txt(filepath, db_manager, logger=print):
    employees = defaultdict(lambda: defaultdict(list))
    unique_employees = set()

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = [l.strip() for l in f if l.strip()]

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 8:
            continue
        matricula = parts[2]
        nome = parts[3]
        iomd = int(parts[5])
        dt_str = f"{parts[6]} {parts[7]}"
        dt = try_parse_datetime(dt_str)
        if not dt:
            continue
        
        unique_employees.add((matricula, nome))
        employees[matricula][dt.date().isoformat()].append({
            "iomd": iomd,
            "datetime": dt,
            "nome": nome
        })
    
    logger(f"Funcionários detectados: {len(unique_employees)}")
    
    for matricula, nome in unique_employees:
        db_manager.insert_funcionario({"matricula": matricula, "nome": nome})

    for matricula, dias in employees.items():
        for data, pontos in dias.items():
            pontos.sort(key=lambda x: x["datetime"])
            
            periodos_trabalhados = []
            minutos_trabalhados = 0
            
            entrada_manha = None
            saida_manha = None
            entrada_tarde = None
            saida_tarde = None
            
            for ponto in pontos:
                if ponto["iomd"] == 0:
                    if entrada_manha is None:
                        entrada_manha = ponto["datetime"]
                    elif entrada_tarde is None and ponto["datetime"].hour >= 12:
                        entrada_tarde = ponto["datetime"]
                elif ponto["iomd"] == 4:
                    if saida_manha is None and entrada_manha:
                        saida_manha = ponto["datetime"]
                    elif saida_tarde is None and entrada_tarde:
                        saida_tarde = ponto["datetime"]
                        
            if entrada_manha and saida_manha:
                schedule_start_morning = datetime.strptime(f"{data} 07:30", "%Y-%m-%d %H:%M")
                final_entry = max(entrada_manha, schedule_start_morning)
                minutes_late = (entrada_manha - schedule_start_morning).total_seconds() / 60
                delay_deduction_minutes = calculate_deduction(minutes_late)
                
                duration_minutes = (saida_manha - final_entry).total_seconds() / 60
                minutos_trabalhados += max(duration_minutes - delay_deduction_minutes, 0)
                periodos_trabalhados.append({
                    "entrada": str(entrada_manha),
                    "saida": str(saida_manha),
                    "minutos_brutos": (saida_manha - entrada_manha).total_seconds() / 60,
                    "deducao_minutos": delay_deduction_minutes,
                    "minutos_liquidos": max(duration_minutes - delay_deduction_minutes, 0)
                })

            if entrada_tarde and saida_tarde:
                schedule_start_afternoon = datetime.strptime(f"{data} 13:00", "%Y-%m-%d %H:%M")
                final_entry = max(entrada_tarde, schedule_start_afternoon)
                minutes_late = (entrada_tarde - schedule_start_afternoon).total_seconds() / 60
                delay_deduction_minutes = calculate_deduction(minutes_late)
                
                duration_minutes = (saida_tarde - final_entry).total_seconds() / 60
                minutos_trabalhados += max(duration_minutes - delay_deduction_minutes, 0)
                periodos_trabalhados.append({
                    "entrada": str(entrada_tarde),
                    "saida": str(saida_tarde),
                    "minutos_brutos": (saida_tarde - entrada_tarde).total_seconds() / 60,
                    "deducao_minutos": delay_deduction_minutes,
                    "minutos_liquidos": max(duration_minutes - delay_deduction_minutes, 0)
                })
            
            if minutos_trabalhados > 0:
                minutos_excedentes = minutos_trabalhados - 8.8 * 60
                db_manager.update_banco_horas(matricula, minutos_excedentes)
                db_manager.insert_horas_trabalhadas({
                    "matricula": matricula,
                    "data": data,
                    "minutos_totais": minutos_trabalhados,
                    "periodos": periodos_trabalhados
                })

class ReportsManager:
    """Gera relatórios a partir dos dados do banco de dados."""
    def __init__(self, db_manager):
        self.db = db_manager

    def get_summary_by_employee(self, start_date, end_date):
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT 
                    f.matricula, 
                    f.nome, 
                    h.data, 
                    h.minutos_totais 
                FROM horas_trabalhadas h
                JOIN funcionarios f ON h.matricula = f.matricula
                WHERE h.data BETWEEN ? AND ?
                ORDER BY f.nome, h.data
            """, (start_date, end_date))
            
            data = cursor.fetchall()
            if not data:
                return []
            
            df = pd.DataFrame(data, columns=['Matricula', 'Nome', 'Data', 'Minutos_Totais'])
            summary = df.groupby(['Matricula', 'Nome'])['Minutos_Totais'].sum().reset_index()
            summary['Horas_Trabalhadas'] = summary['Minutos_Totais'].apply(format_minutes_to_hms)
            
            return summary.to_dict('records')
        except Exception as e:
            print(f"Erro ao gerar resumo por funcionário: {e}")
            return []

    def get_detailed_report(self, matricula, start_date, end_date):
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT 
                    data, 
                    periodos, 
                    minutos_totais 
                FROM horas_trabalhadas
                WHERE matricula = ? AND data BETWEEN ? AND ?
                ORDER BY data
            """, (matricula, start_date, end_date))
            
            report = []
            for row in cursor.fetchall():
                minutos_totais = row['minutos_totais']
                periodos_data = json.loads(row['periodos'])
                
                details = {
                    'Data': row['data'],
                    'Horas_Totais': format_minutes_to_hms(minutos_totais),
                    'Detalhes_Ponto': []
                }
                
                for periodo in periodos_data:
                    entrada = datetime.strptime(periodo['entrada'], '%Y-%m-%d %H:%M:%S')
                    saida = datetime.strptime(periodo['saida'], '%Y-%m-%d %H:%M:%S')
                    
                    details['Detalhes_Ponto'].append({
                        'Entrada': entrada.strftime('%H:%M'),
                        'Saida': saida.strftime('%H:%M'),
                        'Minutos_Liquidos': format_minutes_to_hms(periodo['minutos']),
                        'Deducao_Atraso': format_minutes_to_hms(periodo.get('deducao_minutos', 0))
                    })
                report.append(details)
            return report
        except Exception as e:
            print(f"Erro ao gerar relatório detalhado: {e}")
            return []

    def get_extra_hours_summary(self):
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT matricula, nome, banco_horas, extras_disponiveis FROM funcionarios ORDER BY nome")
            
            data = cursor.fetchall()
            if not data:
                return []
            
            df = pd.DataFrame(data, columns=['Matricula', 'Nome', 'Banco_Horas_Minutos', 'Extras_Disponiveis_Minutos'])
            df['Banco_Horas'] = df['Banco_Horas_Minutos'].apply(format_minutes_to_hms)
            df['Extras_Disponiveis'] = df['Extras_Disponiveis_Minutos'].apply(format_minutes_to_hms)
            
            return df[['Matricula', 'Nome', 'Banco_Horas', 'Extras_Disponiveis']].to_dict('records')
        except Exception as e:
            print(f"Erro ao gerar resumo de extras: {e}")
            return []

# -------------------------
# INTERFACE GRÁFICA (Tkinter)
# -------------------------
class App:
    def __init__(self, root):
        self.db = DatabaseManager()
        self.reports_manager = ReportsManager(self.db)
        self.root = root
        self.root.title("WN Ponto Certo - WN Analytics")
        self.root.geometry("1100x650")
        self.root.configure(bg="#0a0f24")
        self.setup_ui()

    def setup_ui(self):
        style = {"font": ("Segoe UI", 11, "bold"), "bg": "#1e88e5", "fg": "white",
                 "activebackground": "#1565c0", "activeforeground": "white",
                 "relief": tk.FLAT, "width": 18, "height": 2}

        frame_top = tk.Frame(self.root, bg="#0a0f24")
        frame_top.pack(pady=10)

        tk.Button(frame_top, text="📂 Importar Dados", command=self.on_import, **style).grid(row=0, column=0, padx=10)
        tk.Button(frame_top, text="✏️ Editar Ponto", command=self.on_edit_point, **style).grid(row=0, column=1, padx=10)
        tk.Button(frame_top, text="💰 Pagamento Semanal", command=self.on_weekly_payment, **style).grid(row=0, column=2, padx=10)
        tk.Button(frame_top, text="📊 Relatórios", command=self.on_reports_view, **style).grid(row=0, column=3, padx=10)
        tk.Button(frame_top, text="🚪 Sair", command=self.root.quit, **style).grid(row=0, column=4, padx=10)

        lbl = tk.Label(self.root, text="Área de Log:", font=("Segoe UI", 11), bg="#0a0f24", fg="white")
        lbl.pack(anchor=tk.W, padx=20)
        self.log_area = scrolledtext.ScrolledText(self.root, height=20, bg="#101426", fg="white",
                                                  insertbackground="white", font=("Consolas", 10))
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    def append_log(self, text):
        self.log_area.insert(tk.END, text + "\n")
        self.log_area.see(tk.END)

    def on_import(self):
        filepath = filedialog.askopenfilename(
            title="Selecione o arquivo TXT (ex: 001_GLog.txt)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if not filepath:
            return
        try:
            self.append_log(f"Arquivo selecionado: {filepath}")
            self.append_log("Iniciando importação e processamento...")
            import_glog_txt(filepath, self.db, logger=self.append_log)
            self.append_log("Processamento concluído ✅")
        except Exception as e:
            self.append_log(f"Erro: {e}")
            messagebox.showerror("Erro", str(e))

    def on_edit_point(self):
        win = tk.Toplevel(self.root)
        win.title("Editar/Incluir Ponto")
        win.geometry("500x600")
        win.configure(bg="#0a0f24")

        frame_form = tk.Frame(win, bg="#0a0f24")
        frame_form.pack(padx=20, pady=20)

        tk.Label(frame_form, text="Funcionário:", bg="#0a0f24", fg="white").grid(row=0, column=0, pady=5)
        funcionarios = self.db.get_all_funcionarios()
        nomes = [f"{f['matricula']} - {f['nome']}" for f in funcionarios]
        cmb_func = ttk.Combobox(frame_form, values=nomes, state="readonly")
        cmb_func.grid(row=0, column=1, pady=5)

        tk.Label(frame_form, text="Selecione a Data:", bg="#0a0f24", fg="white").grid(row=1, column=0, pady=5)
        cal = Calendar(frame_form, selectmode="day", date_pattern="yyyy-mm-dd", background="#101426",
                       foreground="white", headersbackground="#1e88e5", headersforeground="white",
                       bordercolor="#1e88e5", normalbackground="#101426", normalforeground="white")
        cal.grid(row=1, column=1, pady=10)

        tk.Label(frame_form, text="Entrada Manhã:", bg="#0a0f24", fg="white").grid(row=2, column=0, pady=5)
        frame_in_m = tk.Frame(frame_form, bg="#0a0f24")
        frame_in_m.grid(row=2, column=1)
        ent_in_m_h = tk.Entry(frame_in_m, width=4)
        ent_in_m_h.pack(side=tk.LEFT)
        tk.Label(frame_in_m, text=":", bg="#0a0f24", fg="white").pack(side=tk.LEFT)
        ent_in_m_m = tk.Entry(frame_in_m, width=4)
        ent_in_m_m.pack(side=tk.LEFT)

        tk.Label(frame_form, text="Saída Manhã:", bg="#0a0f24", fg="white").grid(row=3, column=0, pady=5)
        frame_out_m = tk.Frame(frame_form, bg="#0a0f24")
        frame_out_m.grid(row=3, column=1)
        ent_out_m_h = tk.Entry(frame_out_m, width=4)
        ent_out_m_h.pack(side=tk.LEFT)
        tk.Label(frame_out_m, text=":", bg="#0a0f24", fg="white").pack(side=tk.LEFT)
        ent_out_m_m = tk.Entry(frame_out_m, width=4)
        ent_out_m_m.pack(side=tk.LEFT)

        tk.Label(frame_form, text="Entrada Tarde:", bg="#0a0f24", fg="white").grid(row=4, column=0, pady=5)
        frame_in_t = tk.Frame(frame_form, bg="#0a0f24")
        frame_in_t.grid(row=4, column=1)
        ent_in_t_h = tk.Entry(frame_in_t, width=4)
        ent_in_t_h.pack(side=tk.LEFT)
        tk.Label(frame_in_t, text=":", bg="#0a0f24", fg="white").pack(side=tk.LEFT)
        ent_in_t_m = tk.Entry(frame_in_t, width=4)
        ent_in_t_m.pack(side=tk.LEFT)

        tk.Label(frame_form, text="Saída Tarde:", bg="#0a0f24", fg="white").grid(row=5, column=0, pady=5)
        frame_out_t = tk.Frame(frame_form, bg="#0a0f24")
        frame_out_t.grid(row=5, column=1)
        ent_out_t_h = tk.Entry(frame_out_t, width=4)
        ent_out_t_h.pack(side=tk.LEFT)
        tk.Label(frame_out_t, text=":", bg="#0a0f24", fg="white").pack(side=tk.LEFT)
        ent_out_t_m = tk.Entry(frame_out_t, width=4)
        ent_out_t_m.pack(side=tk.LEFT)

        lbl_preview = tk.Label(frame_form, text="Total: 00:00:00", bg="#0a0f24", fg="yellow", font=("Segoe UI", 11, "bold"))
        lbl_preview.grid(row=6, column=0, columnspan=2, pady=10)

        def calcular_preview():
            total_minutes = 0
            periodos = self.get_manual_periods(
                cal.get_date(), ent_in_m_h, ent_in_m_m, ent_out_m_h, ent_out_m_m,
                ent_in_t_h, ent_in_t_m, ent_out_t_h, ent_out_t_m
            )
            for p in periodos:
                total_minutes += p['minutos']
            lbl_preview.config(text=f"Total: {format_minutes_to_hms(total_minutes)}")

        def salvar():
            matricula_nome = cmb_func.get()
            if not matricula_nome:
                messagebox.showerror("Erro", "Selecione um funcionário.")
                return
            
            matricula = matricula_nome.split(" - ")[0]
            data = cal.get_date()
            
            periodos = self.get_manual_periods(
                data, ent_in_m_h, ent_in_m_m, ent_out_m_h, ent_out_m_m,
                ent_in_t_h, ent_in_t_m, ent_out_t_h, ent_out_t_m
            )
            
            if not periodos:
                messagebox.showerror("Erro", "Nenhum período de ponto válido inserido.")
                return

            minutos_totais = sum(p['minutos'] for p in periodos)
            
            self.db.insert_horas_trabalhadas({
                "matricula": matricula,
                "data": data,
                "minutos_totais": minutos_totais,
                "periodos": periodos
            })
            
            messagebox.showinfo("Sucesso", "Alteração efetuada com sucesso.")
            
            ent_in_m_h.delete(0, tk.END); ent_in_m_m.delete(0, tk.END)
            ent_out_m_h.delete(0, tk.END); ent_out_m_m.delete(0, tk.END)
            ent_in_t_h.delete(0, tk.END); ent_in_t_m.delete(0, tk.END)
            ent_out_t_h.delete(0, tk.END); ent_out_t_m.delete(0, tk.END)
            lbl_preview.config(text="Total: 00:00:00")
            
        tk.Button(frame_form, text="Calcular Prévia", bg="#f9a825", fg="black", command=calcular_preview).grid(row=7, column=0, columnspan=2, pady=5)
        tk.Button(frame_form, text="Salvar", bg="#43a047", fg="white", command=salvar).grid(row=8, column=0, columnspan=2, pady=15)

    def get_manual_periods(self, data_str, ent_in_m_h, ent_in_m_m, ent_out_m_h, ent_out_m_m, ent_in_t_h, ent_in_t_m, ent_out_t_h, ent_out_t_m):
        periodos = []
        try:
            entrada_m_str = f"{int(ent_in_m_h.get()):02d}:{int(ent_in_m_m.get()):02d}"
            saida_m_str = f"{int(ent_out_m_h.get()):02d}:{int(ent_out_m_m.get()):02d}"
            entrada_m_dt = datetime.strptime(f"{data_str} {entrada_m_str}", "%Y-%m-%d %H:%M")
            saida_m_dt = datetime.strptime(f"{data_str} {saida_m_str}", "%Y-%m-%d %H:%M")
            if saida_m_dt < entrada_m_dt:
                saida_m_dt += timedelta(days=1)
            duracao_m = (saida_m_dt - entrada_m_dt).total_seconds() / 60
            if duracao_m > 0:
                periodos.append({"entrada": str(entrada_m_dt), "saida": str(saida_m_dt), "minutos": duracao_m})
        except ValueError:
            pass
        try:
            entrada_t_str = f"{int(ent_in_t_h.get()):02d}:{int(ent_in_t_m.get()):02d}"
            saida_t_str = f"{int(ent_out_t_h.get()):02d}:{int(ent_out_t_m.get()):02d}"
            entrada_t_dt = datetime.strptime(f"{data_str} {entrada_t_str}", "%Y-%m-%d %H:%M")
            saida_t_dt = datetime.strptime(f"{data_str} {saida_t_str}", "%Y-%m-%d %H:%M")
            if saida_t_dt < entrada_t_dt:
                saida_t_dt += timedelta(days=1)
            duracao_t = (saida_t_dt - entrada_t_dt).total_seconds() / 60
            if duracao_t > 0:
                periodos.append({"entrada": str(entrada_t_dt), "saida": str(saida_t_dt), "minutos": duracao_t})
        except ValueError:
            pass
        return periodos
    
    def on_weekly_payment(self):
        win = tk.Toplevel(self.root)
        win.title("Pagamento Semanal")
        win.geometry("500x550")
        win.configure(bg="#0a0f24")

        frame_form = tk.Frame(win, bg="#0a0f24")
        frame_form.pack(padx=20, pady=20)

        tk.Label(frame_form, text="Funcionário:", bg="#0a0f24", fg="white").grid(row=0, column=0, pady=5, sticky="w")
        funcionarios = self.db.get_all_funcionarios()
        nomes = [f"{f['matricula']} - {f['nome']}" for f in funcionarios]
        cmb_func = ttk.Combobox(frame_form, values=nomes, state="readonly")
        cmb_func.grid(row=0, column=1, pady=5, sticky="ew")

        tk.Label(frame_form, text="Salário Semanal (R$):", bg="#0a0f24", fg="white").grid(row=1, column=0, pady=5, sticky="w")
        ent_salario = tk.Entry(frame_form)
        ent_salario.grid(row=1, column=1, pady=5, sticky="ew")
        
        tk.Label(frame_form, text="Data Início (Semana):", bg="#0a0f24", fg="white").grid(row=2, column=0, pady=5, sticky="w")
        cal_start = Calendar(frame_form, selectmode="day", date_pattern="yyyy-mm-dd", background="#101426",
                       foreground="white", headersbackground="#1e88e5", headersforeground="white",
                       bordercolor="#1e88e5", normalbackground="#101426", normalforeground="white")
        cal_start.grid(row=2, column=1, pady=5)

        tk.Label(frame_form, text="Data Fim (Semana):", bg="#0a0f24", fg="white").grid(row=3, column=0, pady=5, sticky="w")
        cal_end = Calendar(frame_form, selectmode="day", date_pattern="yyyy-mm-dd", background="#101426",
                       foreground="white", headersbackground="#1e88e5", headersforeground="white",
                       bordercolor="#1e88e5", normalbackground="#101426", normalforeground="white")
        cal_end.grid(row=3, column=1, pady=5)
        
        lbl_info = tk.Label(frame_form, text="", bg="#0a0f24", fg="yellow", font=("Segoe UI", 10))
        lbl_info.grid(row=4, column=0, columnspan=2, pady=10)

        def gerar_recibo():
            matricula_nome = cmb_func.get()
            if not matricula_nome:
                messagebox.showerror("Erro", "Selecione um funcionário.")
                return
            
            matricula = matricula_nome.split(" - ")[0]
            nome = matricula_nome.split(" - ")[1]
            
            try:
                salario_semanal = float(ent_salario.get())
                start_date = cal_start.get_date()
                end_date = cal_end.get_date()
            except ValueError:
                messagebox.showerror("Erro", "Salário ou data inválida.")
                return

            self.db.update_salario(matricula, salario_semanal)
            
            minutos_trabalhados = sum(self.db.get_horas_trabalhadas_periodo(matricula, start_date, end_date))
            
            horas_semanais = minutos_trabalhados / 60
            horas_esperadas = 44
            
            saldo_minutos = (horas_semanais - horas_esperadas) * 60
            
            funcionario = self.db.get_funcionario_info(matricula)
            banco_horas_atual = funcionario['banco_horas']
            extras_disponiveis = funcionario['extras_disponiveis']
            
            if saldo_minutos < 0:
                if banco_horas_atual >= abs(saldo_minutos):
                    self.db.update_banco_horas(matricula, saldo_minutos)
                elif extras_disponiveis >= 240:
                    self.db.update_extras_disponiveis(matricula, -240)
                    self.db.update_banco_horas(matricula, 240 + saldo_minutos)
                else:
                    messagebox.showinfo("Aviso", "Horas negativas e banco de horas/extras insuficientes.")

            valor_liquido = salario_semanal
            if saldo_minutos > 0:
                horas_extras_pagas = saldo_minutos / 60
                valor_hora_padrao = salario_semanal / 44
                valor_pago_extra = horas_extras_pagas * valor_hora_padrao * 1.5
                valor_liquido += valor_pago_extra
            else:
                valor_pago_extra = 0
            
            novo_funcionario = self.db.get_funcionario_info(matricula)
            
            recibo_path = f"Recibo_{nome}_{start_date}_a_{end_date}.pdf"
            c = canvas.Canvas(recibo_path, pagesize=A4)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(cm * 2, 27 * cm, "Recibo de Pagamento Semanal")
            
            c.setFont("Helvetica", 12)
            c.drawString(cm * 2, 26 * cm, f"Funcionário: {nome}")
            c.drawString(cm * 2, 25.5 * cm, f"Período: {start_date} a {end_date}")
            c.drawString(cm * 2, 25 * cm, "-" * 50)
            
            c.drawString(cm * 2, 24 * cm, f"Salário Base: R$ {salario_semanal:.2f}")
            c.drawString(cm * 2, 23.5 * cm, f"Horas Extras (50%): R$ {valor_pago_extra:.2f}")
            c.drawString(cm * 2, 23 * cm, f"Valor Total: R$ {valor_liquido:.2f}")
            c.drawString(cm * 2, 22.5 * cm, "-" * 50)
            
            c.drawString(cm * 2, 21.5 * cm, "Resumo de Horas:")
            c.drawString(cm * 2, 21 * cm, f"Total de Horas Trabalhadas: {horas_semanais:.2f}h")
            c.drawString(cm * 2, 20.5 * cm, f"Novo Saldo no Banco de Horas: {format_minutes_to_hms(novo_funcionario['banco_horas'])}")
            c.drawString(cm * 2, 20 * cm, f"Extras Disponíveis: {format_minutes_to_hms(novo_funcionario['extras_disponiveis'])}")
            
            c.drawString(cm * 2, 10 * cm, "Assinatura do Funcionário: ___________________________")
            
            c.save()
            
            recibo_dados = {
                'matricula': matricula,
                'data_emissao': datetime.now().isoformat(),
                'periodo_inicio': start_date,
                'periodo_fim': end_date,
                'valor_pago': valor_liquido
            }
            self.db.insert_recibo(recibo_dados)
            
            messagebox.showinfo("Sucesso", f"Recibo gerado: {recibo_path}")
            os.startfile(recibo_path)

        tk.Button(frame_form, text="Gerar Recibo", command=gerar_recibo).grid(row=5, column=0, columnspan=2, pady=15)
    
    def on_reports_view(self):
        win = tk.Toplevel(self.root)
        win.title("Relatórios")
        win.geometry("900x650")
        win.configure(bg="#0a0f24")

        style = ttk.Style()
        style.configure("Treeview", background="#101426", foreground="white", fieldbackground="#101426")
        style.configure("Treeview.Heading", background="#1e88e5", foreground="white", font=("Segoe UI", 10, "bold"))
        
        # Frame de controle de período
        frame_period = tk.Frame(win, bg="#0a0f24")
        frame_period.pack(pady=10)
        
        tk.Label(frame_period, text="Data Início:", bg="#0a0f24", fg="white").pack(side=tk.LEFT, padx=5)
        cal_start = Calendar(frame_period, selectmode="day", date_pattern="yyyy-mm-dd", width=12)
        cal_start.pack(side=tk.LEFT, padx=5)
        
        tk.Label(frame_period, text="Data Fim:", bg="#0a0f24", fg="white").pack(side=tk.LEFT, padx=5)
        cal_end = Calendar(frame_period, selectmode="day", date_pattern="yyyy-mm-dd", width=12)
        cal_end.pack(side=tk.LEFT, padx=5)
        
        def reload_reports():
            start_date = cal_start.get_date()
            end_date = cal_end.get_date()
            self.load_summary_report(tree_summary, start_date, end_date)
            self.load_extras_report(tree_extras) # Extras report doesn't need date range
        
        tk.Button(frame_period, text="Atualizar", command=reload_reports).pack(side=tk.LEFT, padx=10)

        notebook = ttk.Notebook(win)
        notebook.pack(pady=10, expand=True, fill="both")

        # Aba de Resumo por Funcionário
        frame_summary = ttk.Frame(notebook)
        notebook.add(frame_summary, text='Resumo de Horas')

        tree_summary = ttk.Treeview(frame_summary, columns=("Matrícula", "Nome", "Horas Trabalhadas"), show="headings")
        tree_summary.heading("Matrícula", text="Matrícula")
        tree_summary.heading("Nome", text="Nome")
        tree_summary.heading("Horas Trabalhadas", text="Horas Trabalhadas")
        tree_summary.pack(fill="both", expand=True)
        
        self.load_summary_report(tree_summary, datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d"))

        # Aba de Banco de Horas e Extras
        frame_extras = ttk.Frame(notebook)
        notebook.add(frame_extras, text='Banco de Horas / Extras')
        
        tree_extras = ttk.Treeview(frame_extras, columns=("Matrícula", "Nome", "Banco de Horas", "Extras Disponíveis"), show="headings")
        tree_extras.heading("Matrícula", text="Matrícula")
        tree_extras.heading("Nome", text="Nome")
        tree_extras.heading("Banco de Horas", text="Banco de Horas")
        tree_extras.heading("Extras Disponíveis", text="Extras Disponíveis")
        tree_extras.pack(fill="both", expand=True)

        self.load_extras_report(tree_extras)
        
    def load_summary_report(self, treeview, start_date, end_date):
        for i in treeview.get_children():
            treeview.delete(i)
        
        summary_data = self.reports_manager.get_summary_by_employee(start_date, end_date)
        for item in summary_data:
            treeview.insert("", "end", values=(item['Matricula'], item['Nome'], item['Horas_Trabalhadas']))

    def load_extras_report(self, treeview):
        for i in treeview.get_children():
            treeview.delete(i)
            
        extras_data = self.reports_manager.get_extra_hours_summary()
        for item in extras_data:
            treeview.insert("", "end", values=(item['Matricula'], item['Nome'], item['Banco_Horas'], item['Extras_Disponiveis']))

# -------------------------
# MAIN
# -------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()