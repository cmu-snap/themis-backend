from django import forms

class ExperimentForm(forms.Form):
    website = forms.URLField(label='Website')
    filename = forms.URLField(label='File URL')
    btlbw = forms.IntegerField(label='BTLBW', required='False')
    rtt = forms.IntegerField(label='RTT', required='False')
    queue_size = forms.IntegerField(label='Queue size', required='False')
