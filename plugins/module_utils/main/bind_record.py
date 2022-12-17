from ansible.module_utils.basic import AnsibleModule

from ansible_collections.ansibleguy.opnsense.plugins.module_utils.base.handler import \
    ModuleSoftError
from ansible_collections.ansibleguy.opnsense.plugins.module_utils.base.api import \
    Session
from ansible_collections.ansibleguy.opnsense.plugins.module_utils.helper.main import \
    simplify_translate, get_multiple_matching
from ansible_collections.ansibleguy.opnsense.plugins.module_utils.base.base import Base


class Record:
    CMDS = {
        'add': 'addRecord',
        'del': 'delRecord',
        'set': 'setRecord',
        'search': 'get',
        'toggle': 'toggleRecord',
    }
    API_KEY = 'record'
    API_KEY_1 = 'record'
    API_KEY_2 = 'records'
    API_MOD = 'bind'
    API_CONT = 'record'
    API_CONT_REL = 'service'
    API_CMD_REL = 'reconfigure'
    FIELDS_CHANGE = ['value']
    FIELDS_ALL = ['domain', 'name', 'type', 'enabled']
    FIELDS_ALL.extend(FIELDS_CHANGE)
    FIELDS_TYPING = {
        'bool': ['enabled'],
        'select': ['type', 'domain'],
    }
    EXIST_ATTR = 'record'

    def __init__(
            self, module: AnsibleModule, result: dict, cnf: dict = None,
            session: Session = None, fail_verify: bool = True, fail_proc: bool = True
    ):
        self.m = module
        self.p = self.m.params if cnf is None else cnf  # to allow override by bind_record_multi
        self.r = result
        self.s = Session(module=module) if session is None else session
        self.fail_verify = fail_verify
        self.fail_proc = fail_proc
        self.exists = False
        self.existing = []
        self.record = {}
        self.call_cnf = {  # config shared by all calls
            'module': self.API_MOD,
            'controller': self.API_CONT,
        }
        self.existing_entries = None
        self.existing_domains = None
        self.exists_rr = False
        self.b = Base(instance=self)

    def check(self):
        if self.p['state'] == 'present' and self.p['value'] is None:
            self._error(
                'You need to supply a value to create the record '
                f"'{self.p['name']}.{self.p['domain']}'"
            )

        # custom matching as dns round-robin allows for multiple records to match..
        if self.existing_entries is None:
            self.existing_entries = self.b.search()

        if self.existing_domains is None:
            self.existing_domains = self.search_call_domains()

        if len(self.existing_domains) == 0:
            self._error('No existing domain found! Create one before managing its records.')

        domain_found = False
        for uuid, dom in self.existing_domains.items():
            if dom['domainname'] == self.p['domain']:
                self.p['domain'] = uuid
                domain_found = True
                break

        if not domain_found:
            self._error(
                f"The provided domain '{self.p['domain']}' was not found! "
                'You may have to create it before managing its records.'
            )

        self.existing = get_multiple_matching(
            module=self.m, existing_items=self.existing_entries,
            compare_item=self.p, match_fields=self.p['match_fields'],
            simplify_func=self._simplify_existing,
        )

        self.exists_rr = len(self.existing) > 1
        self.exists = len(self.existing) == 1

        if self.exists_rr:
            self.r['diff']['before'] = self.existing

        else:
            if self.exists:
                self.record = self.existing[0]
                self.r['diff']['before'] = self.record
                self.call_cnf['params'] = [self.record['uuid']]

            if self.p['state'] == 'present':
                self.r['diff']['after'] = self.b.build_diff(data=self.p)

    def search_call_domains(self) -> dict:
        return self.s.get(cnf={
            **self.call_cnf, **{'command': self.CMDS['search'], 'controller': 'domain'}
        })['domain']['domains']['domain']

    def _error(self, msg: str, verification: bool = True):
        if (verification and self.fail_verify) or (not verification and self.fail_proc):
            self.m.fail_json(msg)

        else:
            self.m.warn(msg)
            raise ModuleSoftError

    def _delete_rr(self):
        self.r['diff']['after'] = {}

        for record in self.existing:
            self.call_cnf['params'] = [record['uuid']]
            self.delete()

    def _simplify_existing(self, record: dict) -> dict:
        # makes processing easier
        return simplify_translate(
            existing=record,
            typing=self.FIELDS_TYPING,
        )

    def process(self):
        if self.exists_rr or self.p['round_robin']:
            # round-robin exists
            if not self.p['round_robin']:
                if self.p['state'] == 'present':
                    self._error(
                        msg='Multiple records with the provided domain/type/name combination exist! '
                            "To create 'round_robin' records - set the argument to 'true'. "
                            "Else remove all existing records by re-calling the module with 'state=absent'",
                        verification=False,
                    )

                else:
                    if self.exists_rr:
                        self._delete_rr()

                    else:
                        self.delete()

            else:
                if self.p['state'] == 'present':
                    self._diff_rr()
                    self.create()

                else:
                    self._delete_rr()

        else:
            # single record
            self.b.process()

    def _diff_rr(self):
        def _key(item: dict, idx: int) -> str:
            return f"{item['type']}:{item['name']}.{item['domain']}#{idx}"

        _before = {}
        _after = {}

        _idx = 0
        for e in self.existing:
            _before[_key(item=e, idx=_idx)] = e
            _idx += 1

        _new = self.b.build_diff(data=self.p)
        _after[_key(item=_new, idx=_idx)] = _new

        self.r['diff']['after'] = {**_before, **_after}
        self.r['diff']['before'] = _before

    def get_existing(self) -> list:
        return self.b.get_existing()

    def create(self):
        self.b.create()

    def update(self):
        self.b.update(enable_switch=True)

    def delete(self):
        self.b.delete()

    def reload(self):
        self.b.reload()