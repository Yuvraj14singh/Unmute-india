from django.db import migrations
from django.utils import timezone

def seed_petition(apps, schema_editor):
    Petition = apps.get_model('indiaApp', 'Petition')
    Signature = apps.get_model('indiaApp', 'PetitionSignature')
    Demand = apps.get_model('indiaApp', 'StudentDemand')
    petition, _ = Petition.objects.get_or_create(
        slug='demand-resignation-dharmendra-pradhan',
        defaults={
            'title':'Demand the Resignation of Union Education Minister Dharmendra Pradhan',
            'eyebrow_text':'EDUCATION ACCOUNTABILITY · STUDENT PETITION',
            'short_heading':'Students demand responsibility, not excuses.',
            'summary':'Support an evidence-led demand for transparent investigation, examination reform, protection of peaceful student voices and accountability from the Union Education Ministry.',
            'full_description':'Unmute India provides this petition as a peaceful, evidence-led channel for students and citizens to ask for public responsibility. A petition records a public demand; it is not proof of wrongdoing. Sources and official responses must be reviewed and labelled transparently.',
            'why_it_matters':'Examination disruption and uncertainty can affect years of preparation, family resources and student wellbeing. Students deserve a transparent, time-bound account of failures and corrective action.',
            'primary_demand':'We call for the resignation of Union Education Minister Dharmendra Pradhan and a transparent, time-bound public accountability process.',
            'additional_demands':'Independent investigation into examination failures\nPublic release of verified findings\nExamination security reforms\nProtection of peaceful student protesters\nRespectful public response to student concerns\nSupport for affected students and families\nA time-bound response from the Education Ministry',
            'questions':'Who accepted responsibility?\nWhy were students forced to protest repeatedly?\nWhy was transparent information delayed?\nWhat reforms have actually been implemented?\nWill an independent report be published?\nWhy should students trust the system again?',
            'target_person':'Dharmendra Pradhan',
            'target_authority':'Union Education Ministry',
            'petition_category':'resignation',
            'petition_status':'published',
            'signature_goal':1000,
            'allow_signatures':True,
            'is_featured':True,
            'published_at':timezone.now(),
            'disclaimer':'This petition expresses a public demand and does not present allegations as proven facts. Evidence must be independently reviewed and official responses will be displayed when verified.',
            'closing_statement':'Students demand responsibility, not excuses.',
        }
    )
    seen = set()
    for signature in Signature.objects.filter(petition__isnull=True).order_by('created_at'):
        normalized = signature.email.strip().lower()
        signature.normalized_email = normalized
        if normalized in seen:
            signature.moderation_status = 'duplicate'
            signature.save()
            continue
        seen.add(normalized)
        signature.petition = petition
        signature.is_verified = signature.verified
        signature.moderation_status = 'valid' if signature.verified else 'pending'
        signature.save()
    demand_titles = [
        'Resignation of Dharmendra Pradhan','Independent time-bound investigation','Transparent public accountability report','Examination-system reforms','Protection of peaceful protesters','Public apology for remarks against students','Support for affected students and families','Time-bound response from the Education Ministry'
    ]
    for order, title in enumerate(demand_titles, 1):
        Demand.objects.get_or_create(title=title, defaults={'priority':order,'display_order':order,'status':'raised','related_petition':petition,'is_published':True,'is_featured':order <= 4})

def reverse_seed(apps, schema_editor):
    pass

class Migration(migrations.Migration):
    dependencies = [('indiaApp','0004_petition_petitionsource_petitionupdate_studentdemand_and_more')]
    operations = [migrations.RunPython(seed_petition, reverse_seed)]
