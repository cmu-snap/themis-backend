from django import forms
from ccamonitor.models import Experiment
import re

class ExperimentForm(forms.ModelForm):
    class Meta:
        model = Experiment
        fields = [
            'website',
            'filename',
            'btlbw',
            'rtt',
            'queue_size',
            'test',
            'competing_ccalg',
        ]

    # Strip http:// or https:// from website
    def clean_website(self):
        data = self.cleaned_data['website']
        p = re.compile('^https?://')
        m = p.match(data)
        if m:
            data = data[m.end():]
        return data


