import {
  Award,
  BookOpen,
  Calendar,
  ChefHat,
  DoorOpen,
  Home,
  Lock,
  Mail,
  MessageSquare,
  Mic,
  NotebookPen,
  Salad,
  ShoppingCart,
  Store,
  Trophy,
  User,
  type LucideIcon,
} from "lucide-react";

// Information architecture for the member shell (UX_KONZEPT §2): a flat 17-link row becomes a
// grouped, icon-led navigation so there is a mental model of "where things live". The same model
// feeds the desktop sidebar and the mobile bottom-bar/Mehr-sheet. Labels reuse the existing
// `nav.*` i18n keys; group headings use new `nav.group.*` keys (DE+EN).
export type NavItem = {
  to: string;
  /** i18n key for the visible label. */
  labelKey: string;
  icon: LucideIcon;
};

export type NavGroup = {
  /** i18n key for the group heading (sidebar). */
  labelKey: string;
  items: NavItem[];
};

export const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav.group.everyday",
    items: [
      { to: "/today", labelKey: "nav.today", icon: Home },
      { to: "/tasks", labelKey: "nav.tasks", icon: Award },
      { to: "/shopping", labelKey: "nav.shopping", icon: ShoppingCart },
      { to: "/calendar", labelKey: "nav.calendar", icon: Calendar },
    ],
  },
  {
    labelKey: "nav.group.kitchen",
    items: [
      { to: "/recipes", labelKey: "nav.recipes", icon: ChefHat },
      { to: "/mealplan", labelKey: "nav.mealplan", icon: Salad },
    ],
  },
  {
    labelKey: "nav.group.household",
    items: [
      { to: "/rooms", labelKey: "nav.rooms", icon: DoorOpen },
      { to: "/rewards", labelKey: "nav.rewards", icon: Trophy },
      { to: "/challenge", labelKey: "nav.challenge", icon: Award },
      { to: "/marketplace", labelKey: "nav.marketplace", icon: Store },
    ],
  },
  {
    labelKey: "nav.group.storage",
    items: [
      { to: "/notes", labelKey: "nav.notes", icon: NotebookPen },
      { to: "/letters", labelKey: "nav.letters", icon: Mail },
      { to: "/guides", labelKey: "nav.guides", icon: BookOpen },
      { to: "/vault", labelKey: "nav.vault", icon: Lock },
      { to: "/capture", labelKey: "nav.capture", icon: Mic },
    ],
  },
  {
    labelKey: "nav.group.account",
    items: [
      { to: "/", labelKey: "nav.account", icon: User },
      { to: "/feedback", labelKey: "nav.feedback", icon: MessageSquare },
    ],
  },
];

// The few entries that live in the mobile bottom-tab bar; everything else lives behind „Mehr".
export const MOBILE_PRIMARY: NavItem[] = [
  { to: "/today", labelKey: "nav.today", icon: Home },
  { to: "/tasks", labelKey: "nav.tasks", icon: Award },
  { to: "/recipes", labelKey: "nav.recipes", icon: ChefHat },
  { to: "/calendar", labelKey: "nav.calendar", icon: Calendar },
];
