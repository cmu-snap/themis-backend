from django import forms

class ExperimentForm(forms.Form):
    website = forms.URLField(label='Website')
    filename = forms.URLField(label='File URL')
    btlbw = forms.IntegerField(label='BTLBW', required=False, min_value=0)
    rtt = forms.IntegerField(label='RTT', required=False, min_value=0)
    queue_size = forms.IntegerField(label='Queue size', required=False, min_value=0)
    #test = forms.CharField(label='Test', required=False)
    #competing_ccalg = forms.CharField(label='Competing ccalg', required=False)
