from time import monotonic


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self,settings,repository,task_id,prices=None):
        self.settings,self.repository,self.task_id=settings,repository,task_id
        self.prices=prices
        self.started=monotonic()
        self.used={"rounds":0,"search_requests":0,"fetch_requests":0,"model_call_attempts":0,
                   "model_requests":0,"input_tokens":0,"output_tokens":0,"duration_seconds":0,
                   "cost_estimate_usd":None,"cost_note":"未配置可核实的完整单价，不估算金额；使用请求次数及 token 硬上限。",
                   "model_usage_complete":True,"tool_usage_complete":True,"cost_reserved_upper_usd":0,"price_profile":prices}

    def save(self):
        self.used["duration_seconds"]=round(monotonic()-self.started,3)
        if self.prices and self.used['model_usage_complete'] and self.used['tool_usage_complete']:
            p=self.prices
            self.used['cost_estimate_usd']=round(self.used['input_tokens']*p['model_input_per_million']/1e6+self.used['output_tokens']*p['model_output_per_million']/1e6+self.used['search_requests']*p['search_per_request']+self.used['fetch_requests']*p['fetch_per_request'],8)
            self.used['cost_note']='按记录单价的保守估算，忽略缓存、优惠及失败请求减免；不是账单。'
        elif self.prices:
            self.used['cost_estimate_usd']=None
            self.used['cost_note']='用量不完整，金额不可可靠估算；保留调用前预留上限。'
        self.repository.usage(self.task_id,self.used)

    def reserve_cost(self,value):
        if self.settings.max_budget_usd is not None:
            if self.prices is None:
                raise BudgetExceeded()
            if self.used['cost_reserved_upper_usd']+value>self.settings.max_budget_usd:
                raise BudgetExceeded()
        self.used['cost_reserved_upper_usd']=round(self.used['cost_reserved_upper_usd']+value,8)

    def reserve_tools(self,max_results):
        # Reserve worst-case one retry per search and per Fetch before starting a collection.
        if self.used["search_requests"]+2>self.settings.max_search_requests or self.used["fetch_requests"]+max_results*2>self.settings.max_fetch_requests:
            raise BudgetExceeded()
        if self.prices:
            self.reserve_cost(2*self.prices['search_per_request']+max_results*2*self.prices['fetch_per_request'])
        elif self.settings.max_budget_usd is not None:
            raise BudgetExceeded()
        self.save()

    def reserve_model(self,prompt,instructions,max_output):
        # UTF-8 bytes plus protocol allowance are a conservative reservation, not measured tokens.
        upper_input=len((prompt+instructions).encode())+1024
        actual=self.used["input_tokens"]+self.used["output_tokens"]
        if self.used["model_call_attempts"]>=self.settings.max_model_calls or actual+upper_input+max_output>self.settings.max_total_tokens:
            raise BudgetExceeded()
        if self.prices:
            self.reserve_cost(upper_input*self.prices['model_input_per_million']/1e6+max_output*self.prices['model_output_per_million']/1e6)
        elif self.settings.max_budget_usd is not None:
            raise BudgetExceeded()
        self.used["model_call_attempts"]+=1
        self.save()
