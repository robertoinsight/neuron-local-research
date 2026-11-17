import yaml
from typer.testing import CliRunner

from nlr.cli import app

R = CliRunner()


def rodar(*args, cfgp=None):
    pre = ["--config", str(cfgp)] if cfgp else []
    r = R.invoke(app, pre + [str(a) for a in args])
    assert r.exit_code == 0, r.output + repr(r.exception)
    return r.output


def _salvo(cfg, tmp_path):
    p = tmp_path / "config.yaml"
    cfg.salvar(p)
    return p


def test_config_criar_e_biblioteca_preserva_comentarios(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = rodar("config", "criar", "--backend", "lmstudio", "--destino", tmp_path / "config.yaml")
    assert "Criado" in out and (tmp_path / ".env").exists()
    p = tmp_path / "config.yaml"
    texto = p.read_text(encoding="utf-8")
    assert "# " in texto and "lmstudio" in texto
    pasta = tmp_path / "Meus Documentos"
    pasta.mkdir()
    rodar("biblioteca", "adicionar", pasta, cfgp=p)
    novo = p.read_text(encoding="utf-8")
    assert novo.count("\n#") >= texto.count("\n#") - 1  # comentários preservados
    assert yaml.safe_load(novo)["biblioteca"]["pastas"] == [str(pasta.resolve())]
    rodar("biblioteca", "remover", pasta, cfgp=p)
    assert not yaml.safe_load(p.read_text(encoding="utf-8"))["biblioteca"]["pastas"]
    assert "lmstudio" in rodar("config", "mostrar", cfgp=p)


def test_fluxo_completo_cli(cfg, srv, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = _salvo(cfg, tmp_path)
    assert __import__("nlr").__version__ in rodar("versao")
    out = rodar("indexar", cfgp=p)
    assert "7" in out
    assert "contrato.docx" in rodar("biblioteca", "buscar", "multa rescisão contrato", cfgp=p)
    assert "trechos" in rodar("biblioteca", "status", cfgp=p).lower()
    rodar("memoria", "adicionar", "SeuNome prefere respostas curtas", "--tipo", "preferencia", cfgp=p)
    assert "respostas curtas" in rodar("memoria", "listar", cfgp=p)
    assert "respostas curtas" in rodar("memoria", "buscar", "como ele prefere as respostas", cfgp=p)
    out = rodar("perguntar", "qual é a multa do contrato?", "--modo", "biblioteca", cfgp=p)
    assert "[1]" in out and "Fontes" in out
    out = rodar("pesquisar", "multa do contrato", "--fontes", "biblioteca", "--salvar", tmp_path / "rel.md", cfgp=p)
    assert (tmp_path / "rel.md").read_text(encoding="utf-8").startswith("#")
    out = rodar("projeto", "novo", "calculadora simples com testes", "--nome", "calc", "--autonomo", cfgp=p)
    assert "concluido" in out
    lista = rodar("projeto", "listar", cfgp=p)
    assert "calc" in lista
    assert "calc.py" in rodar("projeto", "status", "calc", cfgp=p)
    out = rodar("ferramentas", cfgp=p)
    assert "escrever_arquivo" in out and "data_hora" in out  # embutidas + plugin
    out = rodar("doctor", "--sem-web", "--sem-mcp", cfgp=p)
    assert "Python" in out


def test_config_invalida_mostra_erro_em_portugues(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("modelo:\n  backend: inexistente\n", encoding="utf-8")
    r = R.invoke(app, ["--config", str(p), "config", "mostrar"])
    assert r.exit_code == 2 and "backend" in r.output
