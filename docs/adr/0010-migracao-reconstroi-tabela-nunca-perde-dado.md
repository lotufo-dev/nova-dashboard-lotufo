# Migração pode reconstruir tabela; nunca perde dado

A regra dizia "migração só acrescenta, nunca DROP". O SQLite não muda restrição nem tipo de coluna no lugar: o
jeito seguro é criar a tabela nova, copiar tudo e trocar, e várias migrações já fazem isso. Decidimos que a regra
protege o dado, não o comando: a migração pode reconstruir uma tabela copiando todas as linhas, e nunca apaga
linha nem coluna com dado financeiro. As migrações rodam sozinhas sobre o banco de produção, então continuam
idempotentes.

## Consequências

- Toda migração que reconstrói tabela tem teste que a roda sobre um banco com dados e compara a contagem de linhas
  antes e depois.
