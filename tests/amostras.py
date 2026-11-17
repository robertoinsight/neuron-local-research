"""Gera documentos de exemplo em vários formatos para os testes da biblioteca."""
from __future__ import annotations

import csv
from pathlib import Path


def gerar(pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "notas.md").write_text(
        "# Receita de pão de queijo\n\nMisture polvilho azedo, queijo minas curado e ovos. "
        "Asse a 180 graus por 25 minutos.\n\n## Dica\nUse leite morno para dar liga.\n", encoding="utf-8")
    (pasta / "viagem.txt").write_text(
        "Roteiro de viagem para Ouro Preto: visitar a Igreja de São Francisco de Assis e a Mina du Veloso. "
        "Hospedagem reservada na pousada Chico Rei.\n", encoding="cp1252")
    (pasta / "codigo").mkdir(exist_ok=True)
    (pasta / "codigo" / "motor.py").write_text(
        'import math\n\n\nclass MotorFisica:\n    """Simula gravidade de sprites."""\n\n    def __init__(self, gravidade=9.8):\n'
        '        self.gravidade = gravidade\n\n    def passo(self, vel, dt):\n        return vel + self.gravidade * dt\n\n\n'
        'def distancia(a, b):\n    """Distância euclidiana entre dois pontos."""\n    return math.dist(a, b)\n', encoding="utf-8")
    with open(pasta / "vendas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["produto", "mes", "valor"])
        w.writerow(["teclado mecânico", "janeiro", "350"])
        w.writerow(["mouse gamer", "fevereiro", "180"])
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Estoque"
    ws.append(["item", "quantidade", "deposito"])
    ws.append(["parafuso sextavado", 1200, "Contagem"])
    ws.append(["arruela inox", 800, "Betim"])
    wb.save(pasta / "estoque.xlsx")
    import docx

    d = docx.Document()
    d.add_heading("Contrato de aluguel", 1)
    d.add_paragraph("O valor do aluguel é de R$ 2.300,00, com reajuste anual pelo IPCA.")
    d.add_paragraph("A multa por rescisão antecipada é de três aluguéis.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Locador"
    t.cell(0, 1).text = "Maria Souza"
    t.cell(1, 0).text = "Locatário"
    t.cell(1, 1).text = "SeuNome"
    d.save(pasta / "contrato.docx")
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 8, "Manual do drone X100. Bateria de litio com autonomia de 32 minutos.")
    pdf.add_page()
    pdf.multi_cell(0, 8, "Capitulo 2: calibracao da bussola antes de cada voo, longe de metais.")
    pdf.output(str(pasta / "manual.pdf"))
    return pasta
