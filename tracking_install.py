"""Install consent/events on public pages using the existing verified SSH key."""
from __future__ import annotations
import hashlib,json,re,shlex,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def snippet():
    from brand import TrackingConfig
    config=TrackingConfig()
    if not config.get('enabled'):return ''
    gtm,ga4=config['gtm_public_id'],config['ga4_measurement_id']
    if not re.fullmatch(r'GTM-[A-Z0-9]+',gtm) or not re.fullmatch(r'G-[A-Z0-9]+',ga4):
        raise ValueError('Identificador de medição inválido')
    version=hashlib.sha256((ROOT/'tracking/cml-track.js').read_bytes()).hexdigest()[:12]
    return f'<script id="cml-tracking" defer src="/blog/cml-track.js?v={version}" data-gtm="{gtm}" data-ga4="{ga4}"></script>'

def patch_html(text,*,lp=False):
    text=re.sub(r'<script\b[^>]*\bid="cml-tracking"[^>]*>\s*</script>','',text)
    tag=snippet()
    if not tag or text.count('</head>')!=1:raise ValueError('Medição desabilitada ou HTML não reconhecido')
    text=text.replace('</head>',tag+'</head>',1)
    if lp and '// CML tracking form adapter v1' not in text:
        replacements={
          'if (!valid) return;':"if (!valid) { try { window.CMLTracking?.failed(this, 'validation'); } catch (_) {} return; }",
          'data.enviado_em = new Date().toISOString();':"data.enviado_em = new Date().toISOString();\n    // CML tracking form adapter v1\n    try { Object.assign(data, window.CMLTracking?.payload(this) || {}); } catch (_) {}",
          "if (!response.ok) throw new Error('Falha ao enviar lead');":"if (!response.ok) throw new Error('Falha ao enviar lead');\n      try { window.CMLTracking?.submitted(this); } catch (_) {}",
          '} catch (err) {\n      let message':"} catch (err) {\n      try { window.CMLTracking?.failed(this, 'network'); } catch (_) {}\n      let message"}
        for old,new in replacements.items():
            if text.count(old)!=1:raise ValueError('Formulário mudou; revisar antes de instalar')
            text=text.replace(old,new,1)
    return text

if __name__=='__main__':
    print(snippet())
