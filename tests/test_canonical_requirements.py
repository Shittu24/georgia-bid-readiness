"""Database constraints and review-status tests, using rolled-back synthetic data."""
import copy
import importlib.util
import os
from pathlib import Path
import uuid

import psycopg
from psycopg.types.json import Jsonb
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('base_requirement_tests', ROOT / 'tests/test_requirement_loader.py')
base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
bundle = base.bundle


@pytest.fixture
def setup(bundle):
    if os.environ.get('GBR_RUN_DB_TESTS') != '1':
        pytest.skip('Set GBR_RUN_DB_TESTS=1 against a migrated test database')
    with psycopg.connect(**base.loader.settings(), autocommit=True) as conn:
        with conn.transaction():
            prepared = base.loader.prepare(bundle)
            amended = copy.deepcopy(prepared)
            for r in amended['responses']:
                r['response_id'] += '-addendum'
                r['item']['document_id'] += '-addendum'
                r['record']['document_id'] += '-addendum'
            with conn.cursor() as cur:
                base.seed_sources(cur, prepared)
                base.seed_sources(cur, amended)
                original_doc = prepared['responses'][0]['item']['document_id']
                amended_doc = amended['responses'][0]['item']['document_id']
                cur.execute('SELECT solicitation_id FROM core.documents WHERE document_id=%s',(original_doc,))
                solicitation = cur.fetchone()[0]
                cur.execute("UPDATE core.documents SET solicitation_id=%s,document_type='addendum',amendment_number=1 WHERE document_id=%s",(solicitation,amended_doc))
            base.loader.load(conn, prepared, commit=True)
            base.loader.load(conn, amended, commit=True)
            def candidate(p):
                r=next(r for r in p['responses'] if r['record']['approach']=='zero_shot' and r['item']['page_number']==1)
                return r['response_id']+'-1'
            ctx = dict(conn=conn,sid=solicitation,original=candidate(prepared),amended=candidate(amended),prefix=uuid.uuid4().hex)
            yield ctx
            raise psycopg.Rollback()


def review(ctx, candidate, suffix, decision='accepted', quote='Sign the proposal.'):
    rid=ctx['prefix']+suffix
    payload=dict(requirement='Sign the proposal.',condition=None,deadline_text=None,evidence=[dict(page_number=1,quote=quote)])
    ctx['conn'].execute("""INSERT INTO core.requirement_reviews(review_event_id,candidate_id,decision,reviewer,review_method,reviewed_at,approved_payload,notes)
      VALUES(%s,%s,%s,'test human','human',clock_timestamp(),%s,'Synthetic review')""",(rid,candidate,decision,Jsonb(payload)))
    return rid


def group(ctx, suffix='group', sid=None):
    gid=ctx['prefix']+suffix
    ctx['conn'].execute("INSERT INTO core.canonical_requirements(canonical_id,solicitation_id,topic_label,created_by) VALUES(%s,%s,'Signature obligation','test human')",(gid,sid or ctx['sid']))
    return gid


def assertion(ctx, gid, rid, suffix):
    aid=ctx['prefix']+suffix
    ctx['conn'].execute("INSERT INTO core.canonical_assertions(assertion_id,canonical_id,review_event_id,linked_by,rationale) VALUES(%s,%s,%s,'test human','Same obligation')",(aid,gid,rid))
    return aid


def pair(ctx):
    gid=group(ctx)
    a=assertion(ctx,gid,review(ctx,ctx['original'],'r1'),'a1')
    b=assertion(ctx,gid,review(ctx,ctx['amended'],'r2'),'a2')
    return a,b


def relation(ctx,a,b):
    lid=ctx['prefix']+'link'
    ctx['conn'].execute("INSERT INTO core.amendment_relations(relation_id,earlier_assertion_id,later_assertion_id,relation_type,proposed_by,rationale) VALUES(%s,%s,%s,'clarifies','test human','Synthetic clarification')",(lid,a,b))
    return lid


def relation_review(ctx,lid,suffix,decision='confirmed'):
    ctx['conn'].execute("INSERT INTO core.amendment_relation_reviews(review_id,relation_id,decision,reviewer,review_method,reviewed_at,notes) VALUES(%s,%s,%s,'test human','human',clock_timestamp(),'Checked both sources')",(ctx['prefix']+suffix,lid,decision))


def usable(ctx,lid):
    return ctx['conn'].execute('SELECT usable_reviewed_relation FROM reporting.amendment_relation_status WHERE relation_id=%s',(lid,)).fetchone()[0]


def test_accepted_review_can_be_grouped(setup):
    c=setup; a=assertion(c,group(c),review(c,c['original'],'r'),'a')
    assert c['conn'].execute('SELECT review_is_current FROM reporting.canonical_assertion_status WHERE assertion_id=%s',(a,)).fetchone()[0]


def test_unaccepted_review_rejected(setup):
    c=setup; g=group(c); r=review(c,c['original'],'r',decision='needs_followup')
    with pytest.raises(psycopg.errors.RaiseException,match='accepted human'):
        with c['conn'].transaction(): assertion(c,g,r,'a')


def test_stale_review_rejected(setup):
    c=setup;g=group(c);r=review(c,c['original'],'r');review(c,c['original'],'reopen',decision='needs_followup')
    with pytest.raises(psycopg.errors.RaiseException,match='stale review'):
        with c['conn'].transaction(): assertion(c,g,r,'a')


def test_wrong_quote_rejected(setup):
    c=setup;g=group(c);r=review(c,c['original'],'r',quote='Invented evidence')
    with pytest.raises(psycopg.errors.RaiseException,match='does not match'):
        with c['conn'].transaction(): assertion(c,g,r,'a')


def test_cross_solicitation_group_rejected(setup):
    c=setup;sid=c['prefix']+'other'
    c['conn'].execute("INSERT INTO core.solicitations(solicitation_id,agency_name,solicitation_number,title,source_page_url) VALUES(%s,%s,%s,'Other','https://example.test')",(sid,sid,sid))
    g=group(c,sid=sid);r=review(c,c['original'],'r')
    with pytest.raises(psycopg.errors.RaiseException,match='same solicitation'):
        with c['conn'].transaction(): assertion(c,g,r,'a')


def test_amendment_requires_confirmation(setup):
    c=setup;lid=relation(c,*pair(c)); assert not usable(c,lid)
    relation_review(c,lid,'confirm'); assert usable(c,lid)


def test_reverse_amendment_rejected(setup):
    c=setup;a,b=pair(c)
    with pytest.raises(psycopg.errors.RaiseException,match='direction'):
        with c['conn'].transaction(): relation(c,b,a)


def test_different_groups_rejected(setup):
    c=setup;a=assertion(c,group(c,'g1'),review(c,c['original'],'r1'),'a1')
    b=assertion(c,group(c,'g2'),review(c,c['amended'],'r2'),'a2')
    with pytest.raises(psycopg.errors.RaiseException,match='same canonical group'):
        with c['conn'].transaction(): relation(c,a,b)


def test_reopened_source_disables_relationship(setup):
    c=setup;lid=relation(c,*pair(c));relation_review(c,lid,'confirmed');assert usable(c,lid)
    review(c,c['amended'],'reopened',decision='needs_followup')
    assert not usable(c,lid)


def test_reopened_relation_no_longer_usable(setup):
    c=setup;lid=relation(c,*pair(c));relation_review(c,lid,'confirmed')
    relation_review(c,lid,'reopened',decision='needs_followup');assert not usable(c,lid)


def test_history_cannot_be_overwritten(setup):
    c=setup;gid=group(c)
    with pytest.raises(psycopg.errors.RaiseException,match='append-only'):
        with c['conn'].transaction():
            c['conn'].execute("UPDATE core.canonical_requirements SET topic_label='Overwrite' WHERE canonical_id=%s",(gid,))


def test_automated_relation_confirmation_rejected(setup):
    c=setup;lid=relation(c,*pair(c))
    with pytest.raises(psycopg.errors.CheckViolation):
        with c['conn'].transaction():
            c['conn'].execute("INSERT INTO core.amendment_relation_reviews(review_id,relation_id,decision,reviewer,review_method,reviewed_at,notes) VALUES(%s,%s,'confirmed','machine','automated',clock_timestamp(),'Invalid automatic confirmation')",(c['prefix']+'bad',lid))
