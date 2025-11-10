import io
import base64
from io import BytesIO
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import requests
from django.shortcuts import render

from .forms import ArffUploadForm


def _fig_to_base64(fig):
    buf = BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return img_b64


def _split_dataframe(df, seed=42):
    """Simple aleatorio: 60%/20%/20%"""
    n = len(df)
    rng = np.random.default_rng(seed)
    indices = np.arange(n)
    rng.shuffle(indices)
    t1 = int(0.6 * n)
    t2 = int(0.8 * n)
    train_idx = indices[:t1]
    val_idx = indices[t1:t2]
    test_idx = indices[t2:]
    return df.iloc[train_idx], df.iloc[val_idx], df.iloc[test_idx]


def _stratified_split(df, label_col, seed=42, ratios=(0.6, 0.2, 0.2)):
    """Particionado estratificado por label_col manteniendo proporciones.

    - df: DataFrame original
    - label_col: nombre de la columna categórica para estratificar
    - ratios: tupla con proporciones para (train, val, test)
    """
    assert abs(sum(ratios) - 1.0) < 1e-6, "Las proporciones deben sumar 1.0"
    rng = np.random.default_rng(seed)

    train_parts, val_parts, test_parts = [], [], []
    for label, group in df.groupby(label_col, dropna=False):
        n = len(group)
        idx = np.arange(n)
        rng.shuffle(idx)

        n_train = int(ratios[0] * n)
        n_val = int(ratios[1] * n)
        # Asegurar que no se pierdan filas por redondeos
        n_test = n - n_train - n_val

        train_parts.append(group.iloc[idx[:n_train]])
        val_parts.append(group.iloc[idx[n_train:n_train + n_val]])
        test_parts.append(group.iloc[idx[n_train + n_val:]])

    train_df = pd.concat(train_parts, axis=0).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    val_df = pd.concat(val_parts, axis=0).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    test_df = pd.concat(test_parts, axis=0).sample(frac=1.0, random_state=seed).reset_index(drop=True)
    return train_df, val_df, test_df


def _plot_protocol_histogram(series, title, order=None):
    """Crea un barplot para la distribución de protocol_type y devuelve b64.

    order: lista opcional con el orden deseado de categorías.
    """
    vc = series.astype(str).value_counts()
    if order:
        present = [c for c in order if c in vc.index]
        others = [c for c in vc.index if c not in present]
        ordered = present + others
    else:
        ordered = list(vc.index)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(ordered, vc.loc[ordered].values)
    ax.set_title(title)
    ax.set_ylabel('Frecuencia')
    ax.set_xlabel('protocol_type')
    return _fig_to_base64(fig)


def analyze_arff_view(request):
    context = {'form': ArffUploadForm()}

    if request.method == 'POST':
        form = ArffUploadForm(request.POST, request.FILES)
        if form.is_valid():
            source = form.cleaned_data.get('source')
            file_content = None
            file_name = None

            try:
                if source == 'upload':
                    arff_file = request.FILES.get('arff_file')
                    if not arff_file:
                        context['error'] = 'No se seleccionó ningún archivo.'
                        return render(request, 'analyzer/analyze.html', context)
                    if not arff_file.name.lower().endswith('.arff'):
                        context['error'] = 'El archivo debe tener extensión .arff'
                        return render(request, 'analyzer/analyze.html', context)
                    file_name = arff_file.name
                    raw = arff_file.read()
                    try:
                        file_content = raw.decode('utf-8')
                    except Exception:
                        file_content = raw.decode('latin-1')

                elif source == 'github':
                    github_url = form.cleaned_data.get('github_url')
                    if not github_url:
                        context['error'] = 'Introduce la URL del archivo en GitHub.'
                        return render(request, 'analyzer/analyze.html', context)

                    parsed = urlparse(github_url)
                    if 'github.com' in parsed.netloc and '/blob/' in parsed.path:
                        raw_url = github_url.replace('https://github.com/', 'https://raw.githubusercontent.com/')
                        raw_url = raw_url.replace('/blob/', '/')
                    else:
                        raw_url = github_url

                    resp = requests.get(raw_url, timeout=15)
                    if resp.status_code != 200:
                        context['error'] = f'No se pudo descargar el archivo desde GitHub (status {resp.status_code}).'
                        return render(request, 'analyzer/analyze.html', context)

                    file_name = raw_url.split('/')[-1]
                    file_content = resp.text

                if file_content:
                    # Nombres de atributos
                    attribute_names = []
                    for line in file_content.split('\n'):
                        if line.strip().lower().startswith('@attribute'):
                            parts = line.split()
                            if len(parts) >= 2:
                                attribute_names.append(parts[1].strip("'\""))

                    # Cargar datos
                    df = pd.read_csv(
                        io.StringIO(file_content),
                        comment='@',
                        header=None,
                        na_values=['?']
                    )

                    if len(attribute_names) == len(df.columns):
                        df.columns = attribute_names
                    else:
                        df.columns = [f'Columna_{i+1}' for i in range(len(df.columns))]

                    # Convertir numéricas cuando aplique
                    for c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors='ignore')

                    # Crear splits (como 07_Division_DataSet): si existe protocol_type usar estratificado
                    pt_col = None
                    lower_map = {c.lower(): c for c in df.columns}
                    if 'protocol_type' in lower_map:
                        pt_col = lower_map['protocol_type']

                    if pt_col is not None:
                        train_df, val_df, test_df = _stratified_split(df, pt_col, seed=42)
                    else:
                        train_df, val_df, test_df = _split_dataframe(df, seed=42)

                    # Tabla preview
                    df_html = df.head(200).to_html(
                        classes='table table-hover table-striped',
                        max_rows=200,
                        justify='left',
                        border=0,
                        na_rep='-'
                    )

                    plots = {}

                    # Únicamente las 4 gráficas de protocol_type (dataset, train, val, test) si la columna existe
                    na_counts = df.isna().sum()  # se mantiene por posible uso futuro pero no se grafica
                    if pt_col is not None:
                        try:
                            # Orden especial para TEST: colocar 'tcp' en medio cuando existan 3 categorías típicas
                            uniques = set(df[pt_col].astype(str).unique())
                            desired_test_order = None
                            if 'tcp' in uniques:
                                base = ['udp', 'tcp', 'icmp']
                                desired_test_order = [c for c in base if c in uniques]

                            plots['prot_full'] = _plot_protocol_histogram(df[pt_col], 'protocol_type - Dataset completo')
                            plots['prot_train'] = _plot_protocol_histogram(train_df[pt_col], 'protocol_type - Train')
                            plots['prot_val'] = _plot_protocol_histogram(val_df[pt_col], 'protocol_type - Validación')
                            plots['prot_test'] = _plot_protocol_histogram(test_df[pt_col], 'protocol_type - Test', order=desired_test_order)
                        except Exception:
                            # Si algo falla, no bloquear el flujo
                            pass

                    context.update({
                        'df_html': df_html,
                        'file_name': file_name,
                        'num_rows': df.shape[0],
                        'num_cols': df.shape[1],
                        'plots': plots,
                        'protocol_col': pt_col,
                    })

            except requests.RequestException as re:
                context['error'] = f'Error al descargar desde GitHub: {str(re)}'
            except Exception as e:
                context['error'] = f'Error al procesar el archivo: {str(e)}'

    return render(request, 'analyzer/analyze.html', context)
