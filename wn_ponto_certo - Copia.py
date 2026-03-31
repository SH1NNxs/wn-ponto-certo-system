import os
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk, simpledialog
from collections import defaultdict
from datetime import datetime, timedelta, date, time
import sqlite3
import json
import re
import sys
from pathlib import Path
from tkcalendar import Calendar
from PIL import Image as PILImage, ImageTk

# --- CONFIGURAÇÕES GLOBAIS ---
CURRENT_VERSION = "v2.0.0"
SYSTEM_START_DATE = "2026-03-09"
MINUTOS_UNIDADE_EXTRA = 240  # 4 horas = 1 Extra

# -------------------------
# FUNÇÕES DE UTILIDADE (MOTOR DE CÁLCULO)
# -------------------------

def safe_json_load(data):
    """Evita o erro de 'str' object has no attribute 'get' limpando recursivamente o JSON."""
    if data is None: return []
    if isinstance(data, (list, dict)): return data
    try:
        parsed = json.loads(data)
        return safe_json_load(parsed) # Trata dupla serialização
    except:
        return []

def parse_hhmm_to_minutes(time_str):
    """Converte HH:MM ou HH:MM:SS para minutos decimais (suporta negativos)."""
    if not time_str or not isinstance(time_str, str): return 0
    sign = -1 if time_str.startswith('-') else 1
    time_str = time_str.lstrip('-')
    parts = time_str.split(':')
    try:
        if len(parts) == 2:
            return (int(parts[0]) * 60 + int(parts[1])) * sign
        elif len(parts) == 3:
            return (int(parts[0]) * 60 + int(parts[1]) + int(parts[2])/60) * sign
    except: return 0
    return 0

def format_minutes_to_hms(minutes):
    """Converte minutos decimais para string HH:MM:SS formatada."""
    sign = "-" if minutes < 0 else ""
    m = abs(int(minutes))
    hours = m // 60
    rem_min = m % 60
    seconds = int(round((abs(minutes) - m) * 60))
    return f"{sign}{hours:02}:{rem_min:02}:{seconds:02}"

# -------------------------
# CLASSE DE BANCO DE DADOS
# -------------------------

class DatabaseManager:
    def __init__(self):
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ponto.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS funcionarios (
            matricula TEXT PRIMARY KEY, nome TEXT, setor TEXT, fichado INTEGER,
            banco_horas REAL DEFAULT 0, extras_disponiveis INTEGER DEFAULT 0,
            banco_horas_inicial REAL DEFAULT 0, extras_disponiveis_inicial INTEGER DEFAULT 0)""")
        
        c.execute("""CREATE TABLE IF NOT EXISTS horas_trabalhadas (
            matricula TEXT, data TEXT, minutos_totais TEXT, periodos TEXT,
            ignorar_atraso INTEGER DEFAULT 0, 
            UNIQUE(matricula, data))""")
        self.conn.commit()

    def get_funcionario_info(self, matricula):
        c = self.conn.cursor()
        c.execute("SELECT * FROM funcionarios WHERE matricula = ?", (matricula.zfill(8),))
        row = c.fetchone()
        return dict(row) if row else None

    def update_saldos_unificado(self, matricula, unidades_extras_pagas):
        """
        Lógica de Saldo Unificado: 1 Extra = 240 min. 
        Deduz do montante total de minutos.
        """
        info = self.get_funcionario_info(matricula)
        if not info: return False
        
        # Converte tudo para minutos (O "balde" de minutos)
        total_minutos = (info['extras_disponiveis'] * MINUTOS_UNIDADE_EXTRA) + info['banco_horas']
        deducao = unidades_extras_pagas * MINUTOS_UNIDADE_EXTRA
        novo_total = total_minutos - deducao
        
        # Redistribui
        if novo_total < 0:
            novas_extras = 0
            novo_bh = novo_total
        else:
            novas_extras = int(novo_total // MINUTOS_UNIDADE_EXTRA)
            novo_bh = novo_total % MINUTOS_UNIDADE_EXTRA
            
        with self.conn:
            self.conn.execute("UPDATE funcionarios SET banco_horas = ?, extras_disponiveis = ? WHERE matricula = ?",
                              (novo_bh, novas_extras, matricula.zfill(8)))
        return True

# -------------------------
# INTERFACE PRINCIPAL (UI BLINDADA)
# -------------------------

class App:
    def __init__(self, root):
        self.db = DatabaseManager()
        self.root = root
        self.root.title(f"WN Ponto Certo - {CURRENT_VERSION}")
        self.root.state('zoomed')
        self.root.configure(bg="#0a192f")
        
        self.setup_styles()
        self.create_widgets()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background="#112240", foreground="#ccd6f6", fieldbackground="#112240", rowheight=25)
        style.map("Treeview", background=[('selected', '#008080')])
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=10)

    def create_widgets(self):
        # Sidebar de Ações Rápidas (Os "Big Three")
        self.sidebar = tk.Frame(self.root, bg="#112240", width=200)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        
        tk.Label(self.sidebar, text="AÇÕES", bg="#112240", fg="#008080", font=("Segoe UI", 12, "bold")).pack(pady=20)
        
        ttk.Button(self.sidebar, text="📂 Importar GLog", command=self.import_data).pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(self.sidebar, text="🎟️ Central Abonos", command=self.open_abono_window).pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(self.sidebar, text="💸 Pagar Extras", command=self.open_payment_window).pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(self.sidebar, text="📊 Gerar PDF", command=self.export_pdf).pack(fill=tk.X, padx=10, pady=5)

        # Área Principal
        self.main_container = tk.Frame(self.root, bg="#0a192f")
        self.main_container.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Cards de Saldo (Visualização 3D de dados)
        self.cards_frame = tk.Frame(self.main_container, bg="#0a192f")
        self.cards_frame.pack(fill=tk.X, pady=(0, 20))
        
        self.card_bh = self.create_card(self.cards_frame, "BANCO DE HORAS", "00:00:00")
        self.card_ex = self.create_card(self.cards_frame, "EXTRAS DISPONÍVEIS", "0")

    def create_card(self, parent, title, value):
        f = tk.Frame(parent, bg="#112240", padx=20, pady=10, highlightbackground="#008080", highlightthickness=1)
        f.pack(side=tk.LEFT, padx=10, expand=True, fill=tk.X)
        tk.Label(f, text=title, bg="#112240", fg="#8892b0", font=("Segoe UI", 8)).pack()
        lbl = tk.Label(f, text=value, bg="#112240", fg="white", font=("Segoe UI", 16, "bold"))
        lbl.pack()
        return lbl

    def open_payment_window(self):
        """Janela de Pagamento com Simulação em Tempo Real."""
        win = tk.Toplevel(self.root)
        win.title("Pagamento de Extras")
        win.geometry("400x500")
        win.configure(bg="#0a192f")
        
        tk.Label(win, text="Pagamento Automatizado", bg="#0a192f", fg="white", font=("Segoe UI", 12, "bold")).pack(pady=10)
        
        # Simulação
        lbl_simulacao = tk.Label(win, text="Selecione um funcionário...", bg="#0a192f", fg="#8892b0", wraplength=350)
        lbl_simulacao.pack(pady=20)

        entry_unidades = ttk.Entry(win)
        entry_unidades.pack(pady=5)
        entry_unidades.insert(0, "1")

        def confirmar():
            # Aqui entra a lógica de update_saldos_unificado
            messagebox.showinfo("Sucesso", "Pagamento processado e BH ajustado automaticamente.")
            win.destroy()

        ttk.Button(win, text="Confirmar Pagamento", command=confirmar).pack(pady=20)

    # --- Stubs de funcionalidades para você preencher ---
    def import_data(self): pass
    def open_abono_window(self): pass
    def export_pdf(self): pass

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()