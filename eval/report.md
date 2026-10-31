# Evaluation, 222 customers

## Accuracy per step (deterministic pipeline vs ground_truth.csv)

- segment: 222/222
- all_segments: 222/222
- reason: 222/222
- outcome: 222/222
- block: 222/222
- all_blocks: 222/222
- message_type: 222/222
- strategy: 222/222
- offer: 222/222
- bill: 222/222
- overdue_days: 222/222
- amount: 222/222
- total: 222/222
- conflicts: 222/222
- greeting: 222/222
- human_review: 222/222

## Primary segment confusion matrix (rows = expected, columns = predicted)

```
expected \ got      consistent  declining_activity  dormant  loyalty_candidate  payment_reminder
consistent          45          0                   0        0                  0               
declining_activity  0           32                  0        0                  0               
dormant             0           0                   34       0                  0               
loyalty_candidate   0           0                   0        43                 0               
payment_reminder    0           0                   0        0                  68              
```

## First block reason confusion matrix

```
expected \ got                   account_inactive  consent_missing  cooldown_or_duplicate  data_conflict  dispute_or_complaint_open  email_not_allowed  email_undeliverable  none  payment_arrangement_or_hardship
account_inactive                 10                0                0                      0              0                          0                  0                    0     0                              
consent_missing                  0                 8                0                      0              0                          0                  0                    0     0                              
cooldown_or_duplicate            0                 0                10                     0              0                          0                  0                    0     0                              
data_conflict                    0                 0                0                      10             0                          0                  0                    0     0                              
dispute_or_complaint_open        0                 0                0                      0              9                          0                  0                    0     0                              
email_not_allowed                0                 0                0                      0              0                          9                  0                    0     0                              
email_undeliverable              0                 0                0                      0              0                          0                  9                    0     0                              
none                             0                 0                0                      0              0                          0                  0                    149   0                              
payment_arrangement_or_hardship  0                 0                0                      0              0                          0                  0                    0     8                              
```

## Drafts

- customers with a draft: 149
- grounded (all message_validator_rules checks pass, no injected digits/dates/offers): 149/149
- written by the AI: 0, plain fallback text: 149
- LLM usage: {'llm_calls': 0, 'tokens': 0, 'model': 'mock', 'llm_errors': 0, 'rate_limited': 0, 'embed_errors': 0}
