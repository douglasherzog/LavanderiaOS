# Lavanderia OS

Aplicação web local para controle de ordens de serviço de lavanderia.

## Requisitos
- Windows com Python 3.10+ instalado

## Instalação
```powershell
# 1) Crie e ative o ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Instale as dependências
pip install -r requirements.txt

# 3) Execute o servidor
python run.py
```

Acesse em http://127.0.0.1:5000

Usuário padrão: admin  
Senha: admin

## Funcionalidades
- Login/logout
- CRUD de Usuários, Clientes, Serviços
- OS com itens, cálculo de total

## Estrutura
- `run.py`: inicia o app
- `app/`: pacote principal
  - `__init__.py`: fábrica da aplicação, registro de blueprints
  - `models.py`: modelos do banco (SQLite)
  - `auth.py`: autenticação
  - `users.py`, `clients.py`, `services.py`, `orders.py`: rotas CRUD
  - `templates/`: HTML (Jinja + Bootstrap)
  - `static/`: CSS/JS
