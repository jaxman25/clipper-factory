import Sidebar from '@/components/studio/Sidebar';
import { StudioProvider } from '@/components/studio/StudioProvider';

export const metadata = {
  title: 'Dashboard',
};

export default function DashboardLayout({ children }) {
  return (
    <StudioProvider>
      <div className="min-h-screen bg-ink">
        <Sidebar />
        <div className="lg:pl-[264px]">
          <main className="mx-auto w-full max-w-[1240px] px-5 pb-24 pt-7 sm:px-8 lg:px-10 lg:pt-10">
            {children}
          </main>
        </div>
      </div>
    </StudioProvider>
  );
}
