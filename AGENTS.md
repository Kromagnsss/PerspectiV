# Consignes Agent

A chaque prompt utilisateur de correction, ou de rework, essaye d'en tirer une demande générique pour venir alimenter ce fichier AGENTS.md AVANT de traiter le prompt et stocke cette demande dans le paragraphe "### Consignes automatiques".
Utilise cette nouvelle entrée pour traiter le prompt.

## Verification visuelle

- A chaque version livree, verifier que l'affichage reste lisible dans l'application Streamlit.
- Controler en particulier les titres, filtres, onglets, tableaux, Gantt et zones fixes lors du scroll.
- Verifier que les bandeaux fixes ne masquent pas les grilles ou graphiques et restent assez visibles.
- Tester au minimum la compilation Python et un smoke test Streamlit sur les pages principales.
- Quand une verification visuelle automatisee n'est pas possible, le signaler explicitement dans le compte rendu.

### Consignes automatiques

- Toujours lire `AGENTS.md` avant de traiter une demande de correction ou de rework, puis appliquer les consignes qui s'y trouvent.
- Pour une correction ou un rework, commencer par extraire la règle générique utile de la demande utilisateur et l'ajouter dans cette section avant de modifier l'application.
- Concevoir l'interface principale pour un usage courant en 1920x1080 : vérifier que les contrôles critiques tiennent dans la largeur disponible sans bouton ou texte tronqué.
- Dans les pages Streamlit avec bandeau fixe, regrouper le titre et les filtres principaux dans un seul bandeau visible ; éviter d'empiler plusieurs bandeaux fixes pour une même page.
- Les filtres et actions de navigation placés dans un bandeau fixe doivent tenir sur une seule ligne quand la cible est un écran 1920x1080.
- Faire commencer le contenu de chaque page sous le bandeau fixe au moyen d'un espacement réservé adapté, afin que les tableaux, Gantt et graphiques ne passent pas dessous.
- Les listes déroulantes, menus, popovers et sélecteurs doivent toujours s'afficher au-dessus des grilles, Gantt, graphiques et bandeaux fixes.
- Dans les vues hebdomadaires, réserver explicitement de la place aux deux boutons de navigation de semaine et vérifier que la flèche droite reste visible.
- Dans un bandeau destiné au 1920x1080, garder une marge de sécurité à droite pour les contrôles de navigation ; ne pas utiliser toute la largeur théorique de la page.
- Pour valider l'affichage, privilégier une QA visuelle reproductible qui sauvegarde des captures PNG locales et un rapport JSON d'assertions inspectables.
- Ne pas rendre les bandeaux si compacts qu'ils deviennent difficiles à repérer ; privilégier un fond lisible, une bordure claire, une ombre légère et des libellés visibles.
- En usage local Streamlit, tenir compte de la barre native Streamlit (`Deploy`, menu, contrôle de sidebar) qui peut recouvrir l'application ; la masquer ou l'abaisser si elle gêne l'interface.
- Pour toute distribution serveur ou mise a jour, utiliser des versions explicites, executer une sauvegarde avant migration, controler un endpoint de sante apres redemarrage et prevoir un retour arriere verifiable.
- Toute API ou integration d'agent doit reutiliser les regles metier de l'application, appliquer les droits cote serveur, journaliser les mutations et ne jamais exposer d'acces SQL generique.
- Toute installation Proxmox doit installer et maintenir une commande systeme `update` fonctionnelle, reliee au script de mise a jour versionne du depot, puis verifier sa presence lors des tests d'installation et de mise a jour.
- Un updater ne doit jamais installer une version inferieure sans option explicite, doit verifier que le tag correspond a la version contenue dans l'archive et doit restaurer PostgreSQL dans un schema vide afin que les objets ajoutes par une migration echouee ne bloquent pas le rollback.
- Une migration de reprise doit detecter un schema deja cree mais non marque dans Alembic, valider ses colonnes avant de le reutiliser et refuser clairement tout etat partiel; l'updater doit permettre de choisir explicitement la sauvegarde a restaurer.
- Apres un redemarrage de service, effectuer le healthcheck avec une boucle d'attente qui tolere explicitement les connexions refusees pendant l'initialisation; ne jamais declencher un rollback sur le premier refus de connexion.
- Pour tout module de gestion des risques, centraliser la cotation et les regles d'acceptation dans la couche metier, tracer chaque iteration et verification, et conserver des liens coherents vers les projets et leurs taches.
- Toute vue hierarchique multi-projet doit synchroniser ses filtres et replis entre tableaux et graphiques, preserver les donnees masquees et interdire les relations entre projets.
