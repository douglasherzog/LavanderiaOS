from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, FloatField, IntegerField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Length, Optional, Regexp, EqualTo, NumberRange


class LoginForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired()])
    password = PasswordField("Senha", validators=[DataRequired()])
    remember = BooleanField("Lembrar-me")
    submit = SubmitField("Entrar")


strong_password_rules = [
    Length(min=6, message="Senha deve ter pelo menos 6 caracteres."),
    Regexp(r".*[A-Z].*", message="Senha deve conter ao menos uma letra maiúscula."),
    Regexp(r".*[0-9].*", message="Senha deve conter ao menos um número."),
    Regexp(r".*[^A-Za-z0-9].*", message="Senha deve conter ao menos um caractere especial."),
]


class UserCreateForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired(), Length(min=3, max=80)])
    full_name = StringField("Nome completo", validators=[DataRequired(), Length(min=3, max=120)])
    role = SelectField("Papel", choices=[("admin", "Administrador"), ("user", "Usuário")])
    password = PasswordField(
        "Senha",
        validators=[DataRequired(message="Senha é obrigatória."), *strong_password_rules],
    )
    confirm_password = PasswordField(
        "Confirmar senha",
        validators=[DataRequired(message="Confirmação é obrigatória."), EqualTo("password", message="As senhas não coincidem.")],
    )
    submit = SubmitField("Salvar")


class UserEditForm(FlaskForm):
    username = StringField("Usuário", validators=[DataRequired(), Length(min=3, max=80)])
    full_name = StringField("Nome completo", validators=[DataRequired(), Length(min=3, max=120)])
    role = SelectField("Papel", choices=[("admin", "Administrador"), ("user", "Usuário")])
    # Na edição, a senha é opcional; se fornecida, aplica as mesmas regras
    password = PasswordField("Senha", validators=[Optional(), *strong_password_rules])
    confirm_password = PasswordField(
        "Confirmar senha",
        validators=[Optional(), EqualTo("password", message="As senhas não coincidem.")],
    )
    submit = SubmitField("Salvar")


class ClientForm(FlaskForm):
    name = StringField("Nome", validators=[DataRequired()])
    phone = StringField("Telefone", validators=[Optional()])
    document = StringField("CPF/CNPJ", validators=[Optional()])
    address = StringField("Endereço", validators=[Optional()])
    submit = SubmitField("Salvar")


def _comma_to_dot(value):
    if value is None:
        return value
    try:
        # Normalize monetary strings like "1.234,56" -> "1234.56"
        if isinstance(value, str):
            s = value.strip()
            # keep only digits, comma and dot
            s = ''.join(ch for ch in s if ch.isdigit() or ch in ',.')
            # remove thousand separators: dots that are not decimal when comma exists
            if ',' in s:
                s = s.replace('.', '')
                s = s.replace(',', '.')
            # if multiple dots remain, keep the last as decimal separator
            if s.count('.') > 1:
                parts = s.split('.')
                s = ''.join(parts[:-1]) + '.' + parts[-1]
            return s
        return value
    except Exception:
        return value


class ServiceForm(FlaskForm):
    name = StringField("Serviço", validators=[DataRequired()])
    # usa StringField para permitir máscara com vírgula e validação customizada na view
    price = StringField("Preço", validators=[DataRequired()])
    unit = StringField("Unidade", default="peca")
    submit = SubmitField("Salvar")


def parse_money_to_float(value):
    s = _comma_to_dot(value)
    if s is None or s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None


class OrderForm(FlaskForm):
    client_id = SelectField("Cliente", coerce=int, validators=[DataRequired()])
    status = SelectField("Status", choices=[
        ("pendente", "Pendente"),
        ("em andamento", "Em andamento"),
        ("pronto", "Pronto"),
        ("entregue", "Entregue"),
    ])
    notes = TextAreaField("Observações", validators=[Optional()])
    delivery_date = StringField("Data de Entrega", validators=[Optional()])
    discount = StringField("Desconto", validators=[Optional()])
    surcharge = StringField("Acréscimo", validators=[Optional()])
    submit = SubmitField("Salvar")


class OrderItemForm(FlaskForm):
    service_id = SelectField("Serviço", coerce=int, validators=[DataRequired()])
    description = StringField("Descrição", validators=[Optional()])
    quantity = IntegerField("Quantidade", default=1, validators=[DataRequired(), NumberRange(min=1, message="Quantidade mínima é 1")])
    unit_price = StringField("Preço unitário", validators=[DataRequired()])
    submit = SubmitField("Adicionar Item")


class PaymentForm(FlaskForm):
    amount = StringField("Valor", validators=[DataRequired(message="Informe o valor.")])
    method = SelectField(
        "Forma",
        choices=[
            ("dinheiro", "Dinheiro"),
            ("pix", "PIX"),
            ("cartao", "Cartão"),
            ("transferencia", "Transferência"),
        ],
        default="dinheiro",
    )
    when_type = SelectField(
        "Quando",
        choices=[
            ("entrada", "Entrada"),
            ("retirada", "Retirada"),
            ("apos", "Após"),
        ],
        default="retirada",
    )
    note = StringField("Observação", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Adicionar Pagamento")
