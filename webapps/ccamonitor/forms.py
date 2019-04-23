from django import forms
from ccamonitor.models import Experiment
import re

class BaseModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super(BaseModelForm, self).__init__(*args, **kwargs)
        # Add common css classes to all widgets
        for field in iter(self.fields):
            # Get current classes from Meta
            widget = self.fields[field].widget
            classes = widget.attrs.get("class")
            if widget.input_type != 'checkbox':
                if classes is None:
                    classes = "form-control"
                else:
                    classes += " form-control"
                self.fields[field].widget.attrs.update({'class': classes})

class ExperimentForm(BaseModelForm):
    class Meta:
        model = Experiment
        fields = [
            'website',
            'file_url',
            'btlbw',
            'rtt',
        ]

    CCALGS = (
        ('cubic', 'cubic'),
        ('bbr', 'bbr'),
        ('reno', 'reno'),
    )

    ccalgs = forms.MultipleChoiceField(
            required=True,
            widget=forms.CheckboxSelectMultiple,
            choices=CCALGS)

    # Strip http:// or https:// from website
    def clean_website(self):
        data = self.cleaned_data['website']
        p = re.compile('^https?://')
        m = p.match(data)
        if m:
            data = data[m.end():]
        return data

