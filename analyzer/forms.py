from django import forms


class ArffUploadForm(forms.Form):
    SOURCE_CHOICES = (
        ('upload', 'Subir archivo desde mi equipo'),
        ('github', 'Cargar desde GitHub (URL)'),
    )

    source = forms.ChoiceField(
        choices=SOURCE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='upload',
        label='Fuente'
    )

    arff_file = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'form-control form-control-sm',
                'accept': '.arff'
            }
        ),
        label=''
    )

    github_url = forms.URLField(
        required=False,
        widget=forms.URLInput(
            attrs={
                'class': 'form-control form-control-sm',
                
            }
        ),
        label='URL de GitHub (raw)'
    )
