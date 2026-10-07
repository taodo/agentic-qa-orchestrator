"""Scoped immutable imports/designs, single-attempt generation and explicit link storage."""
from uuid import UUID
from sqlalchemy import select,func,or_
from qa_sentinel.domain.test_specification import TestImport,TestGeneration,CampaignTestSpecification
from qa_sentinel.agents.test_generation import generation_identity
from .campaign_content import row_values,requirement_from
from .models import TestImportRow,TestGenerationRow,TestSpecificationRow,TestRequirementLinkRow,CampaignRequirementRow


def import_from(row):
    return TestImport.model_validate({name:getattr(row,name) for name in TestImport.model_fields})

def generation_from(row):
    return TestGeneration.model_validate({name:getattr(row,'metadata_json' if name=='metadata' else name) for name in TestGeneration.model_fields})

class TestSpecificationRepository:
    def __init__(self,session):self.session=session

    def import_record(self,id):
        row=self.session.get(TestImportRow,str(id))
        return None if row is None else import_from(row)

    def import_identity(self,record):
        row=self.session.scalar(select(TestImportRow).where(TestImportRow.campaign_id==str(record.campaign_id),
            TestImportRow.format==record.format.value,TestImportRow.content_hash==record.content_hash,TestImportRow.contract_version==record.contract_version))
        return None if row is None else import_from(row)

    def resolve_reference(self,campaign_id,ref):
        # Exact UUID first; otherwise exact source-qualified key or unambiguous local key.
        try:ident=str(UUID(ref))
        except ValueError:ident=None
        predicate=CampaignRequirementRow.id==ident if ident is not None else or_(CampaignRequirementRow.logical_key==ref,CampaignRequirementRow.key==ref)
        rows=list(self.session.scalars(select(CampaignRequirementRow).where(CampaignRequirementRow.campaign_id==str(campaign_id),predicate).limit(2)))
        return requirement_from(rows[0]) if len(rows)==1 else None

    def _add_specs(self,records,owner):
        prepared=[CampaignTestSpecification.model_validate(r.model_dump()) for r in records]
        if len(prepared)>100:raise ValueError('Specification output limit')
        for record in prepared:
            if (record.project_id,record.campaign_id,record.provenance.record_id)!=(owner.project_id,owner.campaign_id,owner.id):raise ValueError('Specification provenance ownership mismatch')
            expected_hash=owner.content_hash if isinstance(owner,TestImport) else owner.request_hash
            if record.provenance.content_hash!=expected_hash or record.provenance.contract_version!=owner.contract_version:
                raise ValueError('Specification provenance mismatch')
            expected_origin='IMPORT' if isinstance(owner,TestImport) else 'AI_GENERATED'
            if record.provenance.origin!=expected_origin:raise ValueError('Specification origin mismatch')
            if isinstance(owner,TestImport) and record.provenance.end_line>len(owner.normalized_text.split('\n')):
                raise ValueError('Import provenance outside source')
            for id in record.requirement_ids:
                row=self.session.get(CampaignRequirementRow,str(id))
                if row is None or (row.project_id,row.campaign_id)!=(str(owner.project_id),str(owner.campaign_id)):raise ValueError('Requirement ownership mismatch')
                if isinstance(owner,TestGeneration) and id not in {r.id for r in owner.requirement_versions}:raise ValueError('Unselected requirement link')
        for record in prepared:
            values=row_values(record);ids=values.pop('requirement_ids')
            values.update(import_id=str(owner.id) if isinstance(owner,TestImport) else None,generation_id=None if isinstance(owner,TestImport) else str(owner.id))
            self.session.add(TestSpecificationRow(**values))
            for id in ids:self.session.add(TestRequirementLinkRow(test_spec_id=str(record.id),requirement_id=id,project_id=str(record.project_id),campaign_id=str(record.campaign_id)))
        self.session.flush()

    def add_import(self,record,specs):
        record=TestImport.model_validate(record.model_dump())
        if len(specs)!=record.test_count:raise ValueError('Import count mismatch')
        self.session.add(TestImportRow(**row_values(record)))
        self._add_specs(specs,record)

    def generation(self,id):
        row=self.session.get(TestGenerationRow,str(id))
        return None if row is None else generation_from(row)

    def generation_identity(self,campaign_id,request_hash):
        row=self.session.scalar(select(TestGenerationRow).where(TestGenerationRow.campaign_id==str(campaign_id),TestGenerationRow.request_hash==request_hash,TestGenerationRow.contract_version=='test-specs-v1'))
        return None if row is None else generation_from(row)

    def reserve(self,record):
        record=TestGeneration.model_validate(record.model_dump())
        if record.status!='STARTED':raise ValueError('Reserve STARTED only')
        requirements=[]
        for version in record.requirement_versions:
            row=self.session.get(CampaignRequirementRow,str(version.id))
            if row is None or (row.project_id,row.campaign_id)!=(str(record.project_id),str(record.campaign_id)):raise ValueError('Selected requirement ownership mismatch')
            requirements.append(requirement_from(row))
        versions,identity=generation_identity(requirements)
        if versions!=record.requirement_versions or identity!=record.request_hash:raise ValueError('Requirement snapshot mismatch')
        values=row_values(record);values['metadata_json']=values.pop('metadata')
        self.session.add(TestGenerationRow(**values));self.session.flush()

    def finish(self,record,specs=()):
        record=TestGeneration.model_validate(record.model_dump())
        row=self.session.get(TestGenerationRow,str(record.id))
        if row is None or row.status!='STARTED' or record.status=='STARTED':raise ValueError('Generation cannot be replayed')
        old=generation_from(row)
        for name in ('id','project_id','campaign_id','request_hash','contract_version','requirement_versions','agent','model','started_at'):
            if getattr(old,name)!=getattr(record,name):raise ValueError('Generation identity immutable')
        if record.status!='SUCCEEDED' and specs:raise ValueError('Failed generation cannot produce specs')
        self._add_specs(specs,record)
        row.status,row.finished_at,row.error_code=record.status.value,record.finished_at,record.error_code
        row.metadata_json=None if record.metadata is None else record.metadata.model_dump(mode='json')
        self.session.flush()

    def _specs(self,rows):
        if not rows:return []
        ids=[r.id for r in rows];links={id:[] for id in ids}
        bounded=list(self.session.scalars(select(TestRequirementLinkRow).where(TestRequirementLinkRow.test_spec_id.in_(ids))
            .order_by(TestRequirementLinkRow.test_spec_id,TestRequirementLinkRow.requirement_id).limit(len(ids)*20+1)))
        if len(bounded)>len(ids)*20:raise ValueError('Stored link limit')
        for link in bounded:links[link.test_spec_id].append(link.requirement_id)
        return [CampaignTestSpecification.model_validate({**{name:getattr(r,name) for name in CampaignTestSpecification.model_fields if name!='requirement_ids'},'requirement_ids':links[r.id]}) for r in rows]

    def specification(self,id):
        row=self.session.get(TestSpecificationRow,str(id))
        return None if row is None else self._specs([row])[0]

    @staticmethod
    def _limit(limit):
        if type(limit)is not int or not 1<=limit<=200:raise ValueError('Invalid list limit')
        return limit+1

    def specifications(self,campaign_id,limit):
        rows=list(self.session.scalars(select(TestSpecificationRow).where(TestSpecificationRow.campaign_id==str(campaign_id))
            .order_by(func.qa_utc_microseconds(TestSpecificationRow.created_at),TestSpecificationRow.id).limit(self._limit(limit))))
        return self._specs(rows)

    def imports(self,campaign_id,limit):
        # Metadata projection keeps potentially large normalized imports lazy.
        columns=[c for c in TestImportRow.__table__.c if c.name!='normalized_text']
        return list(self.session.execute(select(*columns).where(TestImportRow.campaign_id==str(campaign_id))
            .order_by(func.qa_utc_microseconds(TestImportRow.created_at),TestImportRow.id).limit(self._limit(limit))).mappings())

    def generations(self,campaign_id,limit):
        return [generation_from(r) for r in self.session.scalars(select(TestGenerationRow).where(TestGenerationRow.campaign_id==str(campaign_id))
            .order_by(func.qa_utc_microseconds(TestGenerationRow.started_at),TestGenerationRow.id).limit(self._limit(limit)))]
