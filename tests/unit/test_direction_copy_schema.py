import re
import pytest
from brandpilot.design_direction import direction_schema


@pytest.mark.parametrize('field,text,valid',[
    ('cta','شاركنا نكهتك المفضلة',True),('cta','قول لنا نكهتك المفضلة في التعليقات',False),
    ('cta','Tell us your favorite',True),('cta','Tell us all about your favorite drink',False),
    ('headline','طاقة طبيعية في كل يوم',True),('headline','One two three four five six seven eight',False)])
def test_provider_schema_matches_the_copy_word_limit(field,text,valid):
    assert bool(re.fullmatch(direction_schema()['properties'][field]['pattern'],text))==valid
