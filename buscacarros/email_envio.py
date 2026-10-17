"""Envio do resumo por e-mail (Gmail com senha de app)."""
import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)


def _brl(v):
    return 'R$ ' + f'{v:,.0f}'.replace(',', '.') if v is not None else '—'


def _pct(v):
    return (f'{v:+.1f}%').replace('.', ',') if v is not None else ''


def top5(carros):
    """Os 5 maiores descontos sobre a FIPE, sem anúncios com alerta."""
    validos = [c for c in carros if c.get('dif_pct') is not None and not c.get('alertas')]
    validos.sort(key=lambda c: c['dif_pct'])
    abaixo = [c for c in validos if c['dif_pct'] < 0][:5]
    return abaixo, (validos[:5] if not abaixo else [])


def corpo_html(dados, carros):
    abaixo, proximos = top5(carros)
    lista = abaixo or proximos
    status = ''.join(
        f"<li>{html.escape(s['site'])}: {'%d anúncios' % s['qtd'] if s['status'] == 'ok' else html.escape(s['mensagem'] or s['status'])}"
        + (f" <span style='color:#56636B'>({html.escape(s['busca'])})</span>" if len(dados['buscas']) > 1 else '') + '</li>'
        for s in dados['status'])
    if abaixo:
        intro = f'<p style="margin:0 0 12px">Os {len(abaixo)} maiores descontos sobre a FIPE nesta rodada (sem anúncios com alerta):</p>'
    elif proximos:
        intro = '<p style="margin:0 0 12px">Nenhum carro abaixo da FIPE nesta rodada. Estes são os mais próximos dela:</p>'
    else:
        intro = '<p style="margin:0 0 12px">Nenhum carro com FIPE identificada nesta rodada.</p>'
    linhas = []
    for c in lista:
        url = c['links'][0]['url']
        cor = '#1F7A52' if c['dif_pct'] < 0 else '#A65F0C'
        foto = (f'<img src="{html.escape(c["foto"])}" width="120" height="90" style="display:block;border-radius:4px;object-fit:cover" alt="">'
                if c.get('foto') else '')
        local = '/'.join(x for x in (c.get('cidade'), c.get('uf')) if x)
        km = f"{c['km']:,} km".replace(',', '.') if c.get('km') is not None else ''
        linhas.append(f'''
<tr>
  <td style="padding:10px 12px 10px 0;vertical-align:top;width:120px"><a href="{html.escape(url)}">{foto}</a></td>
  <td style="padding:10px 0;vertical-align:top;font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1F2A30">
    <a href="{html.escape(url)}" style="color:#1450A3;font-weight:600;font-size:15px;text-decoration:none">{html.escape(c['titulo_exibicao'])}</a><br>
    {c.get('ano_modelo') or ''} · {km} · {html.escape(local)}<br>
    <b style="font-size:16px">{_brl(c['preco'])}</b>
    <span style="color:#56636B"> FIPE {_brl(c['fipe']['valor'])}</span>
    <b style="color:{cor}"> {_pct(c['dif_pct'])}</b>
  </td>
</tr>''')
    tabela = f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse">{"".join(linhas)}</table>' if linhas else ''
    return f'''<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1F2A30;max-width:620px">
<p style="margin:0 0 4px;font-size:18px;font-weight:600">{len(carros)} carros encontrados</p>
<p style="margin:0 0 16px;color:#56636B">{'<br>'.join(html.escape(b['rotulo']) for b in dados['buscas'])}</p>
{intro}{tabela}
<p style="margin:16px 0 4px">O relatório completo, com filtros e ordenação, está em anexo.</p>
<ul style="margin:4px 0 0;padding-left:18px;color:#56636B">{status}</ul>
</div>'''


def enviar(cfg_email, dados, carros, anexo: Path):
    if not cfg_email['ativo']:
        return False, 'envio por e-mail desligado'
    if not (cfg_email['remetente'] and cfg_email['senha_app'] and cfg_email['destinatarios']):
        return False, 'e-mail não configurado (configure em "E-mail do resultado" no painel)'
    msg = EmailMessage()
    abaixo, _ = top5(carros)
    msg['Subject'] = f"Carros: {len(carros)} encontrados" + (f", {len(abaixo)} abaixo da FIPE" if abaixo else '') + f" ({dados['gerado_em'][:5]})"
    msg['From'] = cfg_email['remetente']
    msg['To'] = ', '.join(cfg_email['destinatarios'])
    msg.set_content('Abra este e-mail em um leitor que mostre HTML. O relatório completo está em anexo.')
    msg.add_alternative(corpo_html(dados, carros), subtype='html')
    msg.add_attachment(anexo.read_bytes(), maintype='text', subtype='html', filename=anexo.name)
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=60) as s:
            s.login(cfg_email['remetente'], cfg_email['senha_app'])
            s.send_message(msg)
        return True, 'enviado'
    except smtplib.SMTPAuthenticationError:
        return False, 'o Gmail recusou o login; confira o e-mail e a senha de app no painel'
    except (OSError, smtplib.SMTPConnectError):
        return False, 'não consegui conectar ao Gmail (sem internet ou bloqueio de rede)'
    except Exception as e:
        return False, f'falha no envio: {e}'


def enviar_teste(cfg_email):
    """E-mail curto para conferir a configuração pelo painel."""
    if not (cfg_email['remetente'] and cfg_email['senha_app'] and cfg_email['destinatarios']):
        return False, 'Preencha o Gmail que envia, a senha de app e quem recebe, e salve antes de testar.'
    msg = EmailMessage()
    msg['Subject'] = 'Busca Carro: e-mail de teste'
    msg['From'] = cfg_email['remetente']
    msg['To'] = ', '.join(cfg_email['destinatarios'])
    msg.set_content('Este é um e-mail de teste do Busca Carro. Se você recebeu, o envio dos resultados está funcionando.')
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ssl.create_default_context(), timeout=30) as s:
            s.login(cfg_email['remetente'], cfg_email['senha_app'])
            s.send_message(msg)
        return True, 'E-mail de teste enviado para ' + ', '.join(cfg_email['destinatarios']) + '.'
    except smtplib.SMTPAuthenticationError:
        return False, 'O Gmail recusou o login. Confira o e-mail e a senha de app (não é a senha normal da conta).'
    except (OSError, smtplib.SMTPConnectError):
        return False, 'Não consegui conectar ao Gmail. Confira a internet e tente de novo.'
    except Exception as e:
        return False, f'Não consegui enviar: {e}'
