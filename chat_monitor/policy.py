from copy import deepcopy

def transition(state, tokens, policy, budget, problem=None):
    state=deepcopy(state)
    levels=state.setdefault('levels',{})
    faults=state.setdefault('faults',[])
    if tokens is None:
        state['valid_streak']=0
        if problem not in faults:
            faults.append(problem)
            return state,{'level':'error','reason':problem}
        return state,None
    state['valid_streak']=state.get('valid_streak',0)+1
    if state['valid_streak']>=2: state['faults']=[]
    thresholds=[('50',tokens*100>=budget*50),('75',tokens*100>=budget*75),
                ('90',tokens*100>=budget*90),('over',tokens>budget)]
    current=max((i+1 for i,(_,hit) in enumerate(thresholds) if hit),default=0)
    old=levels.get(policy,0)
    if current>old:
        levels[policy]=current
        return state,{'level':thresholds[current-1][0],
            'crossed':[thresholds[i][0] for i in range(old,current)],'tokens':tokens,'budget':budget}
    return state,None
