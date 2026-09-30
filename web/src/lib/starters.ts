// 15 bilingual starter recipes (P2-S7, Roadmap acceptance). Static content offered on the empty
// gallery for onboarding ("Import oder Starter"); adding one creates a normal household recipe.

type Bilingual = { de: string; en: string };

type LocalizedRecipe = {
  id: string;
  title: Bilingual;
  servings: number;
  tags: string[];
  ingredients: Bilingual[];
  steps: Bilingual;
};

export type StarterRecipe = {
  id: string;
  title: string;
  servings: number;
  tags: string[];
  steps_md: string;
  ingredients: string[];
};

export const STARTERS: LocalizedRecipe[] = [
  {
    id: "spaghetti-aglio-olio",
    title: { de: "Spaghetti Aglio e Olio", en: "Spaghetti Aglio e Olio" },
    servings: 2,
    tags: ["schnell", "vegetarisch"],
    ingredients: [
      { de: "200 g Spaghetti", en: "200 g spaghetti" },
      { de: "3 Knoblauchzehen", en: "3 garlic cloves" },
      { de: "4 EL Olivenöl", en: "4 tbsp olive oil" },
      { de: "1 Prise Chili", en: "1 pinch chilli" },
      { de: "Salz", en: "Salt" },
    ],
    steps: {
      de: "Spaghetti in Salzwasser al dente kochen.\n\nKnoblauch in Scheiben in Olivenöl goldgelb braten, Chili dazugeben.\n\nNudeln abgießen, unterheben, mit Salz abschmecken.",
      en: "Cook the spaghetti al dente in salted water.\n\nGently fry sliced garlic in olive oil until golden, add chilli.\n\nDrain the pasta, toss, season with salt.",
    },
  },
  {
    id: "pfannkuchen",
    title: { de: "Pfannkuchen", en: "Pancakes" },
    servings: 4,
    tags: ["vegetarisch"],
    ingredients: [
      { de: "250 g Mehl", en: "250 g flour" },
      { de: "500 ml Milch", en: "500 ml milk" },
      { de: "3 Eier", en: "3 eggs" },
      { de: "1 Prise Salz", en: "1 pinch salt" },
      { de: "Butter zum Braten", en: "Butter for frying" },
    ],
    steps: {
      de: "Mehl, Milch, Eier und Salz zu einem glatten Teig verrühren.\n\nIn einer Pfanne mit etwas Butter dünne Pfannkuchen goldbraun backen.",
      en: "Whisk flour, milk, eggs and salt into a smooth batter.\n\nFry thin pancakes in a little butter until golden.",
    },
  },
  {
    id: "tomatensuppe",
    title: { de: "Tomatensuppe", en: "Tomato soup" },
    servings: 4,
    tags: ["vegetarisch"],
    ingredients: [
      { de: "1 Zwiebel", en: "1 onion" },
      { de: "800 g Tomate", en: "800 g tomatoes" },
      { de: "500 ml Wasser", en: "500 ml water" },
      { de: "2 EL Olivenöl", en: "2 tbsp olive oil" },
      { de: "Salz, Pfeffer", en: "Salt, pepper" },
    ],
    steps: {
      de: "Zwiebel in Öl glasig dünsten.\n\nTomaten und Wasser dazugeben, 15 Minuten köcheln.\n\nPürieren und mit Salz und Pfeffer abschmecken.",
      en: "Sweat the onion in oil until soft.\n\nAdd tomatoes and water, simmer for 15 minutes.\n\nBlend and season with salt and pepper.",
    },
  },
  {
    id: "ruehrei",
    title: { de: "Rührei", en: "Scrambled eggs" },
    servings: 2,
    tags: ["schnell", "vegetarisch"],
    ingredients: [
      { de: "4 Eier", en: "4 eggs" },
      { de: "2 EL Milch", en: "2 tbsp milk" },
      { de: "1 EL Butter", en: "1 tbsp butter" },
      { de: "Salz, Pfeffer", en: "Salt, pepper" },
    ],
    steps: {
      de: "Eier mit Milch, Salz und Pfeffer verquirlen.\n\nButter in der Pfanne schmelzen, Eier bei mittlerer Hitze cremig rühren.",
      en: "Beat the eggs with milk, salt and pepper.\n\nMelt butter in the pan, stir the eggs over medium heat until creamy.",
    },
  },
  {
    id: "griechischer-salat",
    title: { de: "Griechischer Salat", en: "Greek salad" },
    servings: 2,
    tags: ["schnell", "vegetarisch"],
    ingredients: [
      { de: "3 Tomate", en: "3 tomatoes" },
      { de: "1 Paprika", en: "1 bell pepper" },
      { de: "100 g Käse", en: "100 g feta" },
      { de: "3 EL Olivenöl", en: "3 tbsp olive oil" },
      { de: "Salz, Pfeffer", en: "Salt, pepper" },
    ],
    steps: {
      de: "Tomaten und Paprika in mundgerechte Stücke schneiden.\n\nKäse darüber bröseln, mit Öl, Salz und Pfeffer anmachen.",
      en: "Cut tomatoes and pepper into bite-sized pieces.\n\nCrumble feta over the top, dress with oil, salt and pepper.",
    },
  },
  {
    id: "pesto-nudeln",
    title: { de: "Pesto-Nudeln", en: "Pesto pasta" },
    servings: 2,
    tags: ["schnell", "vegetarisch"],
    ingredients: [
      { de: "250 g Nudeln", en: "250 g pasta" },
      { de: "4 EL Pesto", en: "4 tbsp pesto" },
      { de: "50 g Käse", en: "50 g parmesan" },
      { de: "Salz", en: "Salt" },
    ],
    steps: {
      de: "Nudeln in Salzwasser kochen.\n\nAbgießen, Pesto unterrühren, mit geriebenem Käse bestreuen.",
      en: "Cook the pasta in salted water.\n\nDrain, stir in the pesto, sprinkle with grated cheese.",
    },
  },
  {
    id: "kartoffelsuppe",
    title: { de: "Kartoffelsuppe", en: "Potato soup" },
    servings: 4,
    tags: [],
    ingredients: [
      { de: "600 g Kartoffel", en: "600 g potatoes" },
      { de: "1 Zwiebel", en: "1 onion" },
      { de: "2 Karotte", en: "2 carrots" },
      { de: "800 ml Wasser", en: "800 ml water" },
      { de: "Salz, Pfeffer", en: "Salt, pepper" },
    ],
    steps: {
      de: "Gemüse schälen und würfeln.\n\nIn Wasser 20 Minuten weich kochen.\n\nTeilweise pürieren, mit Salz und Pfeffer abschmecken.",
      en: "Peel and dice the vegetables.\n\nSimmer in water for 20 minutes until soft.\n\nPartly blend, season with salt and pepper.",
    },
  },
  {
    id: "caprese",
    title: { de: "Caprese", en: "Caprese" },
    servings: 2,
    tags: ["schnell", "vegetarisch"],
    ingredients: [
      { de: "3 Tomate", en: "3 tomatoes" },
      { de: "1 Mozzarella", en: "1 ball mozzarella" },
      { de: "Basilikum", en: "Basil" },
      { de: "2 EL Olivenöl", en: "2 tbsp olive oil" },
    ],
    steps: {
      de: "Tomaten und Mozzarella in Scheiben schneiden und abwechselnd anrichten.\n\nMit Basilikum, Öl und Salz garnieren.",
      en: "Slice tomatoes and mozzarella and arrange alternately.\n\nGarnish with basil, oil and salt.",
    },
  },
  {
    id: "bananenbrot",
    title: { de: "Bananenbrot", en: "Banana bread" },
    servings: 8,
    tags: ["vegetarisch"],
    ingredients: [
      { de: "3 Banane", en: "3 bananas" },
      { de: "200 g Mehl", en: "200 g flour" },
      { de: "100 g Zucker", en: "100 g sugar" },
      { de: "2 Eier", en: "2 eggs" },
      { de: "80 g Butter", en: "80 g butter" },
    ],
    steps: {
      de: "Bananen zerdrücken, mit den übrigen Zutaten zu einem Teig verrühren.\n\nBei 180 °C ca. 45 Minuten backen.",
      en: "Mash the bananas, mix with the remaining ingredients into a batter.\n\nBake at 180 °C for about 45 minutes.",
    },
  },
  {
    id: "gemuesecurry",
    title: { de: "Gemüsecurry", en: "Vegetable curry" },
    servings: 4,
    tags: ["vegetarisch"],
    ingredients: [
      { de: "2 Karotte", en: "2 carrots" },
      { de: "1 Paprika", en: "1 bell pepper" },
      { de: "400 ml Sahne", en: "400 ml cream" },
      { de: "200 g Reis", en: "200 g rice" },
      { de: "2 EL Olivenöl", en: "2 tbsp oil" },
    ],
    steps: {
      de: "Reis nach Packung kochen.\n\nGemüse in Öl anbraten, Sahne dazugeben und 10 Minuten köcheln.\n\nMit dem Reis servieren.",
      en: "Cook the rice as per the packet.\n\nFry the vegetables in oil, add cream and simmer for 10 minutes.\n\nServe with the rice.",
    },
  },
  {
    id: "porridge",
    title: { de: "Porridge", en: "Porridge" },
    servings: 1,
    tags: ["schnell", "vegetarisch"],
    ingredients: [
      { de: "50 g Haferflocken", en: "50 g oats" },
      { de: "250 ml Milch", en: "250 ml milk" },
      { de: "1 Banane", en: "1 banana" },
      { de: "1 TL Honig", en: "1 tsp honey" },
    ],
    steps: {
      de: "Haferflocken mit Milch aufkochen und 5 Minuten quellen lassen.\n\nMit Bananenscheiben und Honig servieren.",
      en: "Bring oats and milk to a boil and let swell for 5 minutes.\n\nServe with banana slices and honey.",
    },
  },
  {
    id: "haehnchen-reispfanne",
    title: { de: "Hähnchen-Reispfanne", en: "Chicken rice pan" },
    servings: 3,
    tags: [],
    ingredients: [
      { de: "300 g Hähnchenbrust", en: "300 g chicken breast" },
      { de: "200 g Reis", en: "200 g rice" },
      { de: "1 Paprika", en: "1 bell pepper" },
      { de: "2 EL Olivenöl", en: "2 tbsp oil" },
      { de: "Salz, Pfeffer", en: "Salt, pepper" },
    ],
    steps: {
      de: "Reis kochen.\n\nHähnchen in Würfeln anbraten, Paprika dazugeben.\n\nReis untermischen, mit Salz und Pfeffer abschmecken.",
      en: "Cook the rice.\n\nFry diced chicken, add the pepper.\n\nMix in the rice, season with salt and pepper.",
    },
  },
  {
    id: "linsensuppe",
    title: { de: "Linsensuppe", en: "Lentil soup" },
    servings: 4,
    tags: ["vegetarisch"],
    ingredients: [
      { de: "200 g rote Linsen", en: "200 g red lentils" },
      { de: "1 Zwiebel", en: "1 onion" },
      { de: "2 Karotte", en: "2 carrots" },
      { de: "1 l Wasser", en: "1 l water" },
      { de: "Salz, Pfeffer", en: "Salt, pepper" },
    ],
    steps: {
      de: "Zwiebel und Karotte würfeln und andünsten.\n\nLinsen und Wasser dazugeben, 20 Minuten köcheln.\n\nMit Salz und Pfeffer abschmecken.",
      en: "Dice and sweat the onion and carrot.\n\nAdd lentils and water, simmer for 20 minutes.\n\nSeason with salt and pepper.",
    },
  },
  {
    id: "apfelkompott",
    title: { de: "Apfelkompott", en: "Apple compote" },
    servings: 4,
    tags: ["vegetarisch"],
    ingredients: [
      { de: "4 Apfel", en: "4 apples" },
      { de: "2 EL Zucker", en: "2 tbsp sugar" },
      { de: "100 ml Wasser", en: "100 ml water" },
      { de: "1 Prise Zimt", en: "1 pinch cinnamon" },
    ],
    steps: {
      de: "Äpfel schälen und würfeln.\n\nMit Zucker und Wasser 10 Minuten weich kochen, mit Zimt abschmecken.",
      en: "Peel and dice the apples.\n\nSimmer with sugar and water for 10 minutes until soft, season with cinnamon.",
    },
  },
  {
    id: "bruschetta",
    title: { de: "Bruschetta", en: "Bruschetta" },
    servings: 2,
    tags: ["schnell", "vegetarisch"],
    ingredients: [
      { de: "4 Scheibe Brot", en: "4 slices bread" },
      { de: "3 Tomate", en: "3 tomatoes" },
      { de: "1 Knoblauchzehe", en: "1 garlic clove" },
      { de: "2 EL Olivenöl", en: "2 tbsp olive oil" },
      { de: "Basilikum", en: "Basil" },
    ],
    steps: {
      de: "Brot rösten und mit Knoblauch einreiben.\n\nTomaten würfeln, mit Öl, Basilikum und Salz mischen, auf das Brot geben.",
      en: "Toast the bread and rub with garlic.\n\nDice tomatoes, mix with oil, basil and salt, spoon onto the bread.",
    },
  },
];

export function localizeStarter(recipe: LocalizedRecipe, locale: string): StarterRecipe {
  const lang: "de" | "en" = locale.startsWith("en") ? "en" : "de";
  return {
    id: recipe.id,
    title: recipe.title[lang],
    servings: recipe.servings,
    tags: recipe.tags,
    steps_md: recipe.steps[lang],
    ingredients: recipe.ingredients.map((line) => line[lang]),
  };
}
