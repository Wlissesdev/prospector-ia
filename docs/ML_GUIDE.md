# Aprendizado local

O modelo aprende somente com aprovações e rejeições registradas pelo usuário. Ele usa atributos observáveis: disponibilidade e faixa de seguidores, sinais comerciais registrados, etiquetas de nicho, origem e relação de descoberta, estado de verificação e completude dos dados. Ele não tenta inferir características sensíveis.

O treinamento exige ao menos 8 decisões e 3 exemplos de cada classe. O aplicativo compara regressão logística e árvore de decisão usando validação cruzada estratificada e preserva artefato, versão, tamanho da amostra e métricas. Precision, recall, F1 e PR-AUC de treino são diagnósticos; a F1 de validação serve para comparar os modelos.

A pontuação ordena candidatos para **revisão humana**. Ela não é uma probabilidade garantida de resposta, contratação ou legitimidade e nunca substitui opt-out, recusa ou contato já registrado. Para remover o aprendizado, apague o artefato da pasta `models` e marque um novo treinamento após revisar os dados.
