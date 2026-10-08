"""Find whole-event row groups without reusing or changing any paid row.

Only a completely searched, business-equivalent assignment is a proof. Search
exhaustion is unproven, never permission to choose the first subset found.
"""
import baseline_receipts as BR


def bind(events, mandatory, rows, signature):
    refs=sorted(rows,key=int)
    amounts=[BR.cents(rows[r]['回款明细']) for r in refs]
    budget=[100000]
    def tick():
        budget[0]-=1
        if budget[0]<0:raise OverflowError('fragment matching unproven')
    choices=[]
    try:
        for event in events:
            eligible=[i for i,r in enumerate(refs) if rows[r]['收款时间'] in (event['arrival_date'],event['posting_date'])
                      and amounts[i]<=event['amount_local']]
            options=[]
            suffix=[0]*(len(eligible)+1)
            for j in range(len(eligible)-1,-1,-1):suffix[j]=suffix[j+1]+amounts[eligible[j]]
            def subsets(index,remaining,mask):
                tick()
                if remaining==0:
                    options.append(mask);return
                if index==len(eligible) or suffix[index]<remaining:return
                i=eligible[index]
                if amounts[i]<=remaining:subsets(index+1,remaining-amounts[i],mask|(1<<i))
                subsets(index+1,remaining,mask)
            subsets(0,event['amount_local'],0)
            choices.append(sorted(set(options)))
        # The polynomial distinct-row matcher handles large groups of equal
        # single-row events. This search is needed only if fragmentation exists.
        if not any(mask.bit_count()>1 for opts in choices for mask in opts):
            return 'single_rows'
        all_rows=(1<<len(refs))-1
        order=sorted(range(len(events)),key=lambda i:(i not in mandatory,len(choices[i]),i))
        first=None
        first_facts=None
        assignment={}
        equivalent_previous={}
        for at,i in enumerate(order):
            equivalent_previous[i]=next((j for j in reversed(order[:at])
                                        if (j in mandatory)==(i in mandatory) and signature(events[j])==signature(events[i])),None)
        def search(at,used):
            nonlocal first,first_facts
            tick()
            if at==len(order):
                if used!=all_rows:return
                facts={ref:signature(events[i]) for i,mask in assignment.items()
                       for j,ref in enumerate(refs) if mask&(1<<j)}
                if first is None:
                    first=dict(assignment);first_facts=facts
                elif facts!=first_facts:raise ValueError('non-equivalent receipt ownership')
                return
            i=order[at]
            options=choices[i]+([] if i in mandatory else [0])
            prev=equivalent_previous[i]
            for mask in options:
                if mask&used:continue
                # Equivalent event permutations carry identical business facts.
                # Canonical ordering skips those permutations, including missing.
                rank=mask or all_rows+1
                if prev is not None and rank<(assignment[prev] or all_rows+1):continue
                assignment[i]=mask
                search(at+1,used|mask)
                del assignment[i]
        search(0,0)
        if first is None:return None
        return {i:[ref for j,ref in enumerate(refs) if mask&(1<<j)] for i,mask in first.items()}
    except (OverflowError,ValueError,RecursionError):
        return None
